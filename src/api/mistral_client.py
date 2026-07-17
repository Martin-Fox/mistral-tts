import asyncio
import logging
import base64
import json
import re
from pathlib import Path
from typing import Optional
from mistralai.client import Mistral
from src.api.base_client import BaseTTSClient

logger = logging.getLogger(__name__)

class MistralTTSClient(BaseTTSClient):
    """
    Wrapper for Mistral AI Voxtral API interaction, including voice cloning
    and asynchronous text-to-speech generation.
    """

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = Mistral(api_key=api_key.strip())
        self.model = "voxtral-mini-tts-2603"
        self.voice_sample_path: Optional[Path] = None
        self.voice_id: Optional[str] = None

    async def list_models(self, retry_count: int = 3) -> list:
        """Lists available models from the Mistral API."""
        for attempt in range(retry_count):
            try:
                response = await self.client.models.list_async()
                return [m.id for m in response.data]
            except Exception as e:
                logger.warning(f"Failed to fetch models from API on attempt {attempt + 1}: {e}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return []

    async def list_voices(self, retry_count: int = 3) -> list:
        """
        Lists available voices from the Mistral API.
        Returns a list of voice objects with id and name.
        """
        for attempt in range(retry_count):
            try:
                response = await self.client.audio.voices.list_async()
                return [{"id": v.slug or v.id, "name": v.name} for v in response.items]
            except Exception as e:
                err_msg = str(e).lower()
                is_rate_limit = "429" in err_msg or "rate limit" in err_msg or "rate_limited" in err_msg
                
                logger.warning(f"Failed to fetch voices from API on attempt {attempt + 1}: {e}")
                if attempt < retry_count - 1:
                    wait_time = 10 if is_rate_limit else (2 ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning(f"Using default fallback voices due to failure after {retry_count} attempts.")
                    # Fallback to some common defaults if API fails or key is missing
                    return [
                        {"id": "en_paul_neutral", "name": "Paul (Male - Neutral)"},
                        {"id": "en_sarah_expressive", "name": "Sarah (Female - Expressive)"},
                    ]

    def set_voice_id(self, voice_id: str):
        """Sets a default voice ID to use."""
        self.voice_id = voice_id
        self.voice_sample_path = None

    async def clone_voice(self, audio_path: Path) -> str:
        """
        Sets a reference voice sample for zero-shot cloning.
        Denoises the voice sample in-place using FFmpeg's afftdn filter to improve zero-shot cloning quality.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Voice sample not found at {audio_path}")
        
        logger.info(f"Setting reference voice from {audio_path}")
        
        # Denoise the voice sample using FFmpeg's afftdn filter
        temp_denoised = audio_path.with_suffix(audio_path.suffix + ".denoised")
        try:
            cmd = ["ffmpeg", "-y", "-i", str(audio_path), "-af", "afftdn", str(temp_denoised)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            if process.returncode == 0 and temp_denoised.exists() and temp_denoised.stat().st_size > 0:
                # Atomically replace the original with the denoised version
                temp_denoised.replace(audio_path)
                logger.info("Successfully denoised voice sample in-place using afftdn.")
        except Exception as e:
            logger.warning(f"Failed to denoise voice sample, using original: {e}")
        finally:
            if temp_denoised.exists():
                try:
                    temp_denoised.unlink()
                except Exception:
                    pass

        self.voice_sample_path = audio_path
        self.voice_id = None
        return str(audio_path)

    async def generate_audio(self, text: str, output_path: Path, retry_count: int = 3):
        """
        Generates audio for a given text chunk with exponential backoff.
        """
        if not self.voice_sample_path and not self.voice_id:
            raise ValueError("Either voice sample or voice ID must be set.")

        for attempt in range(retry_count):
            try:
                kwargs = {
                    "model": self.model,
                    "input": text,
                    "response_format": "mp3"
                }

                if self.voice_id:
                    kwargs["voice_id"] = self.voice_id
                elif self.voice_sample_path:
                    # For zero-shot cloning, we might need to send the audio file
                    # The SDK's complete_async might take ref_audio as base64 or a file
                    # Based on my research, some versions take voice_prompt as a file-like object.
                    # Let's try to pass it as a file handle if the SDK supports it, 
                    # or encode to base64 if ref_audio is a string.
                    with open(self.voice_sample_path, "rb") as f:
                        # Assuming the SDK handles file-like objects for ref_audio or similar
                        # In the previous code it was voice_prompt.
                        # Let's use ref_audio and see if it works with bytes or needs base64.
                        # Many modern SDKs handle the upload.
                        
                        # Re-reading the SDK source, ref_audio is OptionalNullable[str].
                        # If it's a string, it's likely base64.
                        audio_data = f.read()
                        kwargs["ref_audio"] = base64.b64encode(audio_data).decode("utf-8")

                response = await self.client.audio.speech.complete_async(**kwargs)
                
                # Check for audio data in the response
                if hasattr(response, 'audio_data'):
                    audio_bytes = base64.b64decode(response.audio_data)
                    output_path.write_bytes(audio_bytes)
                elif hasattr(response, 'audio'):
                    output_path.write_bytes(response.audio)
                elif hasattr(response, 'data'):
                    output_path.write_bytes(response.data)
                else:
                    # Some versions might return a stream or direct bytes
                    logger.error(f"Unexpected response type: {type(response)}")
                    raise ValueError("Could not extract audio data from response")

                logger.info(f"Successfully generated audio for chunk: {output_path}")
                return
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for chunk {output_path}: {e}")
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to generate audio after {retry_count} attempts.")
                    raise

    async def translate_text(self, text: str, source_lang: str, target_lang: str, retry_count: int = 5) -> str:
        """
        Translates a single block of text from source_lang to target_lang using Mistral Large.
        Includes rate-limit aware backoff retry logic (longer wait times for HTTP 429).
        """
        prompt = (
            f"You are a professional translator. Translate the following text from {source_lang} to {target_lang}. "
            f"Maintain the tone, style, and flow of the original. "
            f"Return ONLY the translated text. Do not add any introductory remarks, explanations, or formatting.\n\n"
            f"Text to translate:\n{text}"
        )
        for attempt in range(retry_count):
            try:
                response = await self.client.chat.complete_async(
                    model="mistral-large-latest",
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                if response and response.choices:
                    return response.choices[0].message.content.strip()
                raise ValueError("Empty response from translation API")
            except Exception as e:
                err_msg = str(e).lower()
                is_rate_limit = "429" in err_msg or "rate limit" in err_msg or "rate_limited" in err_msg
                
                logger.warning(f"Translation attempt {attempt + 1} failed: {e}")
                if attempt < retry_count - 1:
                    wait_time = 15 * (attempt + 1) if is_rate_limit else (2 ** attempt)
                    logger.info(f"Rate limit or error encountered. Sleeping for {wait_time}s before retrying...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Translation failed after {retry_count} attempts: {e}")
                    raise

    async def translate_file(self, input_path: Path, source_lang: str, target_lang: str) -> Path:
        """
        Translates a text, srt, epub, or mobi file and saves it in storage/translations/.
        Returns the path to the translated file.
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # Determine file type
        suffix = input_path.suffix.lower()
        is_srt = suffix == ".srt"

        # Read input content
        if suffix == ".epub":
            from src.core.epub_parser import extract_text_from_epub
            content = extract_text_from_epub(input_path)
        elif suffix == ".mobi":
            from src.core.epub_parser import extract_text_from_mobi
            content = extract_text_from_mobi(input_path)
        else:
            with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

        # Normalize line endings
        content = content.replace("\r\n", "\n")
        
        # Prepare output directory
        translations_dir = Path("storage/translations")
        translations_dir.mkdir(parents=True, exist_ok=True)
        
        output_suffix = ".txt" if suffix in {".epub", ".mobi"} else input_path.suffix
        output_filename = f"{input_path.stem}_translated_{target_lang.lower().replace(' ', '_')}{output_suffix}"
        output_path = translations_dir / output_filename



        if is_srt:
            # Parse SRT blocks
            raw_blocks = re.split(r'\n\s*\n', content.strip())
            blocks = []
            for raw_block in raw_blocks:
                lines = raw_block.strip().split('\n')
                if len(lines) >= 3:
                    index = lines[0].strip()
                    timecode = lines[1].strip()
                    text = "\n".join(lines[2:]).strip()
                    blocks.append({"index": index, "timecode": timecode, "text": text})
                elif len(lines) > 0:
                    # Malformed block or empty text
                    index = lines[0].strip()
                    timecode = lines[1].strip() if len(lines) > 1 else ""
                    blocks.append({"index": index, "timecode": timecode, "text": ""})

            # Batch translation using JSON mode
            batch_size = 25
            for i in range(0, len(blocks), batch_size):
                batch = blocks[i:i + batch_size]
                # Filter out empty texts to save API tokens
                non_empty_indices = [idx for idx, b in enumerate(batch) if b["text"]]
                
                if not non_empty_indices:
                    # All blocks in this batch are empty
                    for b in batch:
                        b["translated_text"] = ""
                    continue

                texts_to_translate = [batch[idx]["text"] for idx in non_empty_indices]

                # Call Mistral API in JSON mode
                prompt = (
                    f"You are a professional translator. Translate the following list of subtitle texts from {source_lang} to {target_lang}.\n"
                    f"Maintain the exact meaning, tone, and formatting of each list element.\n"
                    f"Return a JSON object containing a list under the key 'translations'.\n"
                    f"Ensure the output list has exactly the same number of elements ({len(texts_to_translate)}) as the input list, in the exact same order.\n\n"
                    f"Input JSON:\n" + json.dumps({"texts": texts_to_translate}, indent=2)
                )

                # Retry loop with exponential backoff for the batch call
                response = None
                retry_count = 5
                for attempt in range(retry_count):
                    try:
                        response = await self.client.chat.complete_async(
                            model="mistral-large-latest",
                            messages=[{"role": "user", "content": prompt}],
                            response_format={"type": "json_object"}
                        )
                        break
                    except Exception as e:
                        err_msg = str(e).lower()
                        is_rate_limit = "429" in err_msg or "rate limit" in err_msg or "rate_limited" in err_msg
                        
                        logger.warning(f"Batch translation attempt {attempt + 1} failed: {e}")
                        if attempt < retry_count - 1:
                            wait_time = 15 * (attempt + 1) if is_rate_limit else (2 ** attempt)
                            logger.info(f"Rate limit or error encountered. Sleeping for {wait_time}s before retrying...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"Batch translation failed after {retry_count} attempts.")
                            raise

                try:
                    if not response or not response.choices:
                        raise ValueError("No response from Mistral Large API for batch translation")
                    
                    res_content = response.choices[0].message.content
                    res_json = json.loads(res_content)
                    translations = res_json.get("translations", [])

                    if len(translations) != len(texts_to_translate):
                        logger.warning(
                            f"Mismatch in translation batch size: expected {len(texts_to_translate)}, got {len(translations)}. Retrying individually."
                        )
                        # Fallback: translate one by one for this batch
                        translations = []
                        for txt in texts_to_translate:
                            trans = await self.translate_text(txt, source_lang, target_lang)
                            translations.append(trans)

                    # Map translations back to the batch items
                    for idx_in_non_empty, original_batch_idx in enumerate(non_empty_indices):
                        batch[original_batch_idx]["translated_text"] = translations[idx_in_non_empty]

                    # Assign empty strings for any other items
                    for idx, b in enumerate(batch):
                        if idx not in non_empty_indices:
                            b["translated_text"] = ""

                except Exception as e:
                    logger.error(f"Batch processing failed at block {i}: {e}. Falling back to individual translation.")
                    # Fallback for the whole batch
                    for b in batch:
                        if b["text"]:
                            b["translated_text"] = await self.translate_text(b["text"], source_lang, target_lang)
                        else:
                            b["translated_text"] = ""
                
                # Proactive cooldown to prevent rate limit exhaustion
                await asyncio.sleep(1.0)

            # Rebuild SRT content
            output_lines = []
            for b in blocks:
                output_lines.append(f"{b['index']}\n{b['timecode']}\n{b['translated_text']}")
            translated_content = "\n\n".join(output_lines)
            
        else:
            # Plain text file translation
            # Split it into paragraphs or segments to avoid token limit issues
            paragraphs = content.split("\n\n")
            translated_paragraphs = []
            
            # Group paragraphs into chunks of ~3000 chars
            current_chunk = []
            current_len = 0
            chunks = []
            
            for p in paragraphs:
                if current_len + len(p) + 2 > 3000:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [p]
                    current_len = len(p)
                else:
                    current_chunk.append(p)
                    current_len += len(p) + 2
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))

            for chunk in chunks:
                if chunk.strip():
                    translated_chunk = await self.translate_text(chunk, source_lang, target_lang)
                    translated_paragraphs.append(translated_chunk)
                    # Proactive cooldown to prevent rate limit exhaustion
                    await asyncio.sleep(1.0)
                else:
                    translated_paragraphs.append("")

            translated_content = "\n\n".join(translated_paragraphs)

        # Write translated file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(translated_content)

        logger.info(f"Translated file written to {output_path}")
        return output_path
