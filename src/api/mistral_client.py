import asyncio
import logging
import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from mistralai.client import Mistral
from src.api.base_client import BaseTTSClient
from src.core.config import get_translation_model
from src.core.ffmpeg_utils import get_ffmpeg_path

load_dotenv()

logger = logging.getLogger(__name__)

class MistralTTSClient(BaseTTSClient):
    """
    Wrapper for Mistral AI Voxtral API interaction, including voice cloning
    and asynchronous text-to-speech generation.
    """

    def __init__(self, api_key: str, translation_model: Optional[str] = None):
        """
        Initializes the Mistral TTS and translation client.

        Args:
            api_key: Mistral AI API key.
            translation_model: Optional Mistral model identifier for translation.
                Defaults to configured translation model (from get_translation_model()).
        """
        super().__init__(api_key)
        self.client = Mistral(api_key=api_key.strip())
        self.model = "voxtral-mini-tts-2603"
        self.translation_model = translation_model or get_translation_model()
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
            cmd = [get_ffmpeg_path(), "-y", "-i", str(audio_path), "-af", "afftdn", str(temp_denoised)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            if process.returncode == 0 and temp_denoised.exists() and temp_denoised.stat().st_size > 0:
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
        Verifies that the generated file exists, has size > 100 bytes, and has valid duration via ffprobe.

        Args:
            text (str): The text segment to synthesize.
            output_path (Path): Destination path for the generated MP3 chunk.
            retry_count (int): Maximum number of retry attempts on transient failure (default: 3).

        Raises:
            ValueError: If neither voice_sample_path nor voice_id is set, or if API response contains invalid audio data.
            RuntimeError: If generated file is missing, empty (<= 100 bytes), has non-positive duration, or probe fails.
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
                    with open(self.voice_sample_path, "rb") as f:
                        audio_data = f.read()
                        kwargs["ref_audio"] = base64.b64encode(audio_data).decode("utf-8")

                response = await self.client.audio.speech.complete_async(**kwargs)
                
                # Check for audio data in the response
                if getattr(response, 'audio_data', None):
                    audio_bytes = base64.b64decode(response.audio_data)
                    output_path.write_bytes(audio_bytes)
                elif getattr(response, 'audio', None):
                    output_path.write_bytes(response.audio)
                elif getattr(response, 'data', None):
                    output_path.write_bytes(response.data)
                else:
                    logger.error(f"Unexpected response type: {type(response)}")
                    raise ValueError("Could not extract audio data from response")

                # Verify file exists and has size > 100 bytes
                if not output_path.exists() or output_path.stat().st_size <= 100:
                    raise RuntimeError(f"Generated audio file missing or too small (<= 100 bytes): {output_path}")

                # Verify valid duration with ffprobe
                try:
                    probe_cmd = [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(output_path)
                    ]
                    probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
                    duration_val = float(probe_res.stdout.strip())
                    if duration_val <= 0.0:
                        raise ValueError(f"Non-positive duration ({duration_val}s)")
                except Exception as probe_err:
                    raise RuntimeError(f"Generated audio chunk {output_path} verification failed: {probe_err}") from probe_err

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
        Translates a single block of text from source_lang to target_lang using the configured Mistral chat model.
        Includes rate-limit-aware exponential backoff retry logic (with extended wait times for HTTP 429).
        Detects and logs warnings if the response token limit was reached (finish_reason == 'length').

        Args:
            text (str): The raw text segment to translate.
            source_lang (str): Source language name or code (e.g. 'Polish', 'English').
            target_lang (str): Target language name or code (e.g. 'English', 'French').
            retry_count (int): Maximum number of retry attempts on failure (default: 5).

        Returns:
            str: Translated text content stripped of leading/trailing whitespace.

        Raises:
            ValueError: If the translation API returns an empty response.
            Exception: If all retry attempts are exhausted without success.
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
                    model=self.translation_model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                if response and response.choices:
                    choice = response.choices[0]
                    finish_reason = getattr(choice, "finish_reason", None)
                    if finish_reason == "length":
                        logger.error(
                            "Mistral translation exceeded token output capacity (finish_reason='length')."
                        )
                        raise RuntimeError("Mistral translation exceeded token output capacity (finish_reason='length').")
                    return choice.message.content.strip()
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

    async def translate_file(
        self,
        input_path: Path,
        source_lang: str,
        target_lang: str,
        output_filename: Optional[str] = None
    ) -> Path:
        """
        Translates a text, srt, epub, or mobi file and writes it atomically to storage/translations/.
        Splits large paragraphs exceeding 2500 characters to safeguard against token limit truncation.
        Detects finish_reason == 'length', parses SRT cues in JSON batch mode, and preserves input file stem.

        Args:
            input_path (Path): Path to the source file (.txt, .srt, .epub, .mobi).
            source_lang (str): Source language (e.g. 'Polish').
            target_lang (str): Target language (e.g. 'English').
            output_filename (Optional[str]): Custom output filename. If None, defaults to
                                             '{stem}_translated_{target_lang}{suffix}'.

        Returns:
            Path: Path to the atomically written translated file in storage/translations/.

        Raises:
            FileNotFoundError: If input_path does not exist.
            RuntimeError: If translation batching or file writing fails.
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
        
        sanitized_target_lang = re.sub(r"[^a-zA-Z0-9_-]", "_", target_lang.lower())
        output_suffix = ".txt" if suffix in {".epub", ".mobi"} else input_path.suffix
        if not output_filename:
            output_filename = f"{input_path.stem}_translated_{sanitized_target_lang}{output_suffix}"
        output_path = translations_dir / output_filename

        if not output_path.resolve().is_relative_to(translations_dir.resolve()):
            raise ValueError(f"Path traversal detected: {output_filename}")

        if is_srt:
            # Parse SRT blocks cleanly without dropping blocks
            raw_blocks = re.split(r'\n\s*\n+', content.strip())
            blocks = []
            block_counter = 1
            for raw_block in raw_blocks:
                lines = [line.strip() for line in raw_block.strip().split('\n') if line.strip()]
                if not lines:
                    continue
                timing_idx = -1
                for idx, line in enumerate(lines):
                    if '-->' in line:
                        timing_idx = idx
                        break

                if timing_idx != -1:
                    index = lines[0] if timing_idx > 0 else str(block_counter)
                    timecode = lines[timing_idx]
                    text = "\n".join(lines[timing_idx + 1:]).strip()
                    blocks.append({"index": index, "timecode": timecode, "text": text})
                else:
                    index = str(block_counter)
                    timecode = ""
                    text = "\n".join(lines).strip()
                    blocks.append({"index": index, "timecode": timecode, "text": text})
                block_counter += 1

            # Batch translation using JSON mode
            batch_size = 25
            for i in range(0, len(blocks), batch_size):
                batch = blocks[i:i + batch_size]
                # Filter out empty texts to save API tokens
                non_empty_indices = [idx for idx, b in enumerate(batch) if b["text"]]
                
                if not non_empty_indices:
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

                response = None
                retry_count = 5
                for attempt in range(retry_count):
                    try:
                        response = await self.client.chat.complete_async(
                            model=self.translation_model,
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
                    
                    choice = response.choices[0]
                    if getattr(choice, "finish_reason", None) == "length":
                        logger.error("Mistral translation exceeded token output capacity (finish_reason='length').")
                        raise RuntimeError("Mistral translation exceeded token output capacity (finish_reason='length').")

                    res_content = choice.message.content
                    res_json = json.loads(res_content)
                    translations = res_json.get("translations", [])

                    if len(translations) != len(texts_to_translate):
                        logger.warning(
                            f"Mismatch in translation batch size: expected {len(texts_to_translate)}, got {len(translations)}. Retrying individually."
                        )
                        translations = []
                        for txt in texts_to_translate:
                            trans = await self.translate_text(txt, source_lang, target_lang)
                            translations.append(trans)

                    for idx_in_non_empty, original_batch_idx in enumerate(non_empty_indices):
                        batch[original_batch_idx]["translated_text"] = translations[idx_in_non_empty]

                    for idx, b in enumerate(batch):
                        if idx not in non_empty_indices:
                            b["translated_text"] = ""

                except Exception as e:
                    logger.error(f"Batch processing failed at block {i}: {e}. Falling back to individual translation.")
                    for b in batch:
                        if b["text"]:
                            b["translated_text"] = await self.translate_text(b["text"], source_lang, target_lang)
                        else:
                            b["translated_text"] = ""
                
                await asyncio.sleep(1.0)

            # Rebuild SRT content
            output_lines = []
            for b in blocks:
                if b.get("timecode"):
                    output_lines.append(f"{b['index']}\n{b['timecode']}\n{b.get('translated_text', '')}")
                else:
                    output_lines.append(f"{b['index']}\n{b.get('translated_text', '')}")
            translated_content = "\n\n".join(output_lines)
            
        else:
            # Plain text file translation
            # Safely split paragraphs exceeding 2500 characters at sentence boundaries
            raw_paragraphs = content.split("\n\n")
            paragraphs = []
            for p in raw_paragraphs:
                p_clean = p.strip()
                if not p_clean:
                    continue
                if len(p_clean) <= 2500:
                    paragraphs.append(p_clean)
                else:
                    # Split at sentence boundaries
                    sentences = re.split(r'(?<=[.!?])\s+', p_clean)
                    sub_p = ""
                    for s in sentences:
                        s_clean = s.strip()
                        if not s_clean:
                            continue
                        if len(sub_p) + len(s_clean) + 1 <= 2500:
                            sub_p = f"{sub_p} {s_clean}" if sub_p else s_clean
                        else:
                            if sub_p:
                                paragraphs.append(sub_p.strip())
                            # Fallback if a single sentence exceeds 2500 characters
                            if len(s_clean) > 2500:
                                words = s_clean.split(" ")
                                word_p = ""
                                for w in words:
                                    if not w:
                                        continue
                                    if len(word_p) + len(w) + 1 <= 2500:
                                        word_p = f"{word_p} {w}" if word_p else w
                                    else:
                                        if word_p:
                                            paragraphs.append(word_p.strip())
                                        word_p = w
                                sub_p = word_p
                            else:
                                sub_p = s_clean
                    if sub_p and sub_p.strip():
                        paragraphs.append(sub_p.strip())

            # Group paragraphs into chunks of <= 2500 chars
            current_chunk = []
            current_len = 0
            chunks = []

            for p in paragraphs:
                if current_len + len(p) + 2 > 2500:
                    if current_chunk:
                        chunks.append("\n\n".join(current_chunk))
                    current_chunk = [p]
                    current_len = len(p)
                else:
                    current_chunk.append(p)
                    current_len += len(p) + 2
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))

            translated_paragraphs = []
            for chunk in chunks:
                if chunk.strip():
                    translated_chunk = await self.translate_text(chunk, source_lang, target_lang)
                    translated_paragraphs.append(translated_chunk)
                    await asyncio.sleep(1.0)
                else:
                    translated_paragraphs.append("")

            translated_content = "\n\n".join(translated_paragraphs)

        # Write translated file atomically to prevent corrupted or truncated files
        temp_output_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
        try:
            with open(temp_output_path, "w", encoding="utf-8") as f:
                f.write(translated_content)
            temp_output_path.replace(output_path)
        finally:
            if temp_output_path.exists():
                try:
                    temp_output_path.unlink()
                except Exception:
                    pass

        logger.info(f"Translated file written to {output_path}")
        return output_path
