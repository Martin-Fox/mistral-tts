import asyncio
import logging
import base64
import json
import hashlib
from types import SimpleNamespace
import re
import tempfile
import math
from src.core.process_runner import run_process_async, process_budget
from pathlib import Path
from typing import Optional
from mistralai.client import Mistral
from src.api.base_client import BaseTTSClient
from src.api.factory import DEFAULT_TTS_MODELS
from src.api.retry import call_api, validate_retry_settings
from src.core.config import get_translation_model, load_environment
from src.core.cache_io import save_text_atomic, save_json_atomic
from src.core.resource_limits import check_text, ResourceLimits, ResourceLimitExceeded
from src.core.text_splitter import TextSplitter
from src.core.storage_retention import check_storage_budget

load_environment()

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
        process_budget(probe=True)
        request_timeout, _, _ = validate_retry_settings()
        self.client = Mistral(api_key=api_key.strip(), retry_config=None, timeout_ms=max(1, int(request_timeout * 1000)))
        self.model = DEFAULT_TTS_MODELS["mistral"]
        self.translation_model = translation_model or get_translation_model()
        self.voice_sample_path: Optional[Path] = None
        self.voice_sample_bytes = None
        self.voice_id: Optional[str] = None
        self.translation_cache_dir = None

    async def _translation_request(self, attempts=5, **kwargs):
        checkpoint = None
        if self.translation_cache_dir is not None:
            directory = Path(self.translation_cache_dir)
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            key = hashlib.sha256(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()
            checkpoint = directory / f"{key}.json"
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text())
                if not isinstance(saved.get('content'), str) or not saved['content'].strip():
                    raise ValueError('Invalid translation checkpoint')
                return SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=saved['content']), finish_reason=saved.get('finish_reason'))])
        await asyncio.to_thread(check_storage_budget)
        response = await call_api(lambda: self.client.chat.complete_async(**kwargs), attempts=attempts)
        if checkpoint is not None and response and response.choices:
            choice = response.choices[0]
            content = choice.message.content
            reason = getattr(choice, 'finish_reason', None)
            if isinstance(content, str) and content.strip() and reason != 'length':
                save_json_atomic(checkpoint, {'content': content,
                                             'finish_reason': reason if isinstance(reason, str) else None})
        return response

    async def list_models(self, retry_count: int = 3) -> list:
        """Lists available models from the Mistral API."""
        try:
            response = await call_api(lambda: self.client.models.list_async(), attempts=retry_count)
            return [model.id for model in response.data]
        except Exception:
            logger.warning("Could not list models")
            return []

    async def list_voices(self, retry_count: int = 3) -> list:
        try:
            response = await call_api(lambda: self.client.audio.voices.list_async(), attempts=retry_count)
            return [{"id": voice.slug or voice.id, "name": voice.name} for voice in response.items]
        except Exception:
            logger.warning("Could not list voices; using fallback presets")
            return [{"id": "en_paul_neutral", "name": "Paul (Male - Neutral)"},
                    {"id": "en_sarah_expressive", "name": "Sarah (Female - Expressive)"}]

    def set_voice_id(self, voice_id: str) -> None:
        """Sets a default voice ID to use."""
        self.voice_id = voice_id
        self.voice_sample_path = None
        self.voice_sample_bytes = None

    async def clone_voice(self, audio_path: Path) -> str:
        """
        Sets a reference voice sample for zero-shot cloning.
        Denoises a temporary copy using FFmpeg's afftdn filter to improve zero-shot cloning quality.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Voice sample not found at {audio_path}")

        logger.info(f"Setting reference voice from {audio_path}")

        limit = ResourceLimits.from_env().max_voice_upload_bytes
        if audio_path.stat().st_size > limit:
            raise ResourceLimitExceeded("Voice sample exceeds MAX_VOICE_UPLOAD_BYTES")
        self.voice_sample_bytes = None
        with tempfile.TemporaryDirectory(prefix="booksmith-voice-") as directory:
            temp_denoised = Path(directory) / ("denoised" + (audio_path.suffix or ".mp3"))
            try:
                await run_process_async([
                    "ffmpeg", "-y", "-i", str(audio_path), "-af", "afftdn", str(temp_denoised)
                ], timeout=process_budget())
                if not temp_denoised.exists() or not 0 < temp_denoised.stat().st_size <= limit:
                    raise RuntimeError("Denoised voice sample is empty or exceeds its size budget")
                self.voice_sample_bytes = temp_denoised.read_bytes()
                logger.info("Denoised reference voice without modifying the original sample.")
            except Exception as error:
                detail = getattr(error, 'stderr', None)
                if isinstance(detail, bytes):
                    detail = detail.decode('utf-8', errors='replace')[-2000:]
                logger.warning("Denoising failed; using original reference: %s %s", error, detail or '')

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

        kwargs = {
            "model": self.model,
            "input": text,
            "response_format": "mp3"
        }

        if self.voice_id:
            kwargs["voice_id"] = self.voice_id
        elif self.voice_sample_path:
            audio_data = self.voice_sample_bytes
            if audio_data is None:
                with open(self.voice_sample_path, "rb") as stream:
                    audio_data = stream.read(ResourceLimits.from_env().max_voice_upload_bytes + 1)
                if len(audio_data) > ResourceLimits.from_env().max_voice_upload_bytes:
                    raise ResourceLimitExceeded("Voice sample exceeds MAX_VOICE_UPLOAD_BYTES")
            kwargs["ref_audio"] = base64.b64encode(audio_data).decode("utf-8")

        response = await call_api(lambda: self.client.audio.speech.complete_async(**kwargs), attempts=retry_count)

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
            probe_res = await run_process_async(probe_cmd, timeout=process_budget(probe=True))
            duration_val = float(probe_res.stdout.strip())
            if not math.isfinite(duration_val) or duration_val <= 0.0:
                raise ValueError(f"Non-positive duration ({duration_val}s)")
        except Exception as probe_err:
            raise RuntimeError(f"Generated audio chunk {output_path} verification failed: {probe_err}") from probe_err

        logger.info(f"Successfully generated audio for chunk: {output_path}")
        return

    async def translate_text(self, text: str, source_lang: str, target_lang: str, retry_count: int = 5, *, _depth: int = 0) -> str:
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
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Translation input must be non-empty text")
        check_text(text)
        if len(text) > 2500:
            parts = TextSplitter(2500).split(text, extract_srt=False)
            translated = []
            size = 0
            for part in parts:
                result = await self.translate_text(part, source_lang, target_lang, retry_count, _depth=_depth)
                size += len(result) + bool(translated)
                if size > ResourceLimits.from_env().max_text_chars:
                    raise ResourceLimitExceeded("Translated text exceeds MAX_TEXT_CHARS")
                translated.append(result)
            return " ".join(translated)
        prompt = (
            f"You are a professional translator. Translate the following text from {source_lang} to {target_lang}. "
            f"Maintain the tone, style, and flow of the original. "
            f"Return ONLY the translated text. Do not add any introductory remarks, explanations, or formatting.\n\n"
            f"Text to translate:\n{text}"
        )
        response = await self._translation_request(
            attempts=retry_count,
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
                if len(text) > 64 and _depth < 4:
                    parts = TextSplitter(max(1, len(text) // 2)).split(text, extract_srt=False)
                    translated = []
                    for part in parts:
                        translated.append(await self.translate_text(part, source_lang, target_lang, retry_count,
                                                                   _depth=_depth + 1))
                        check_text(" ".join(translated))
                    return " ".join(translated)
                raise RuntimeError("Mistral translation exceeded token output capacity (finish_reason='length').")
            if isinstance(finish_reason, str) and finish_reason != "stop":
                raise ValueError(f"Unsupported translation finish reason: {finish_reason}")
            content = choice.message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Translation API returned empty or non-text content")
            return check_text(content.strip())
        raise ValueError("Empty response from translation API")

    async def translate_file(
        self,
        input_path: Path,
        source_lang: str,
        target_lang: str,
        output_filename: Optional[str] = None,
        input_encoding: Optional[str] = None
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
        from src.core.epub_parser import read_input_text
        content = read_input_text(input_path, encoding=input_encoding)

        check_text(content)

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
            translated_size = 0
            def store_translation(block, text):
                nonlocal translated_size
                translated_size += len(text)
                if translated_size > ResourceLimits.from_env().max_text_chars:
                    raise ResourceLimitExceeded("Translated text exceeds MAX_TEXT_CHARS")
                block["translated_text"] = text

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
            batches, pending = [], []
            for block in blocks:
                candidate = pending + [block]
                payload = json.dumps({"texts": [b["text"] for b in candidate if b["text"]]}, ensure_ascii=False)
                if pending and (len(candidate) > 25 or len(payload) > 2500):
                    batches.append(pending)
                    pending = []
                pending.append(block)
            if pending:
                batches.append(pending)
            for i, batch in enumerate(batches):
                # Filter out empty texts to save API tokens
                non_empty_indices = [idx for idx, b in enumerate(batch) if b["text"]]

                if not non_empty_indices:
                    for b in batch:
                        store_translation(b, "")
                    continue

                texts_to_translate = [batch[idx]["text"] for idx in non_empty_indices]

                if len(json.dumps({"texts": texts_to_translate}, ensure_ascii=False)) > 2500:
                    for b in batch:
                        store_translation(b, await self.translate_text(b["text"], source_lang, target_lang) if b["text"] else "")
                    continue

                # Call Mistral API in JSON mode
                prompt = (
                    f"You are a professional translator. Translate the following list of subtitle texts from {source_lang} to {target_lang}.\n"
                    f"Maintain the exact meaning, tone, and formatting of each list element.\n"
                    f"Return a JSON object containing a list under the key 'translations'.\n"
                    f"Ensure the output list has exactly the same number of elements ({len(texts_to_translate)}) as the input list, in the exact same order.\n\n"
                    f"Input JSON:\n" + json.dumps({"texts": texts_to_translate}, ensure_ascii=False)
                )

                response = await self._translation_request(
                    model=self.translation_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )

                try:
                    if not response or not response.choices:
                        raise ValueError("No response from Mistral Large API for batch translation")

                    choice = response.choices[0]
                    if getattr(choice, "finish_reason", None) == "length":
                        logger.error("Mistral translation exceeded token output capacity (finish_reason='length').")
                        raise RuntimeError("Mistral translation exceeded token output capacity (finish_reason='length').")

                    reason = getattr(choice, "finish_reason", None)
                    if isinstance(reason, str) and reason != "stop":
                        raise ValueError(f"Unsupported translation finish reason: {reason}")
                    res_content = choice.message.content
                    if not isinstance(res_content, str):
                        raise ValueError("Batch response must be text containing JSON")
                    check_text(res_content)
                    res_json = json.loads(res_content)
                    if not isinstance(res_json, dict):
                        raise ValueError("Batch translation must be a JSON object")
                    translations = res_json.get("translations")
                    if not isinstance(translations, list) or any(not isinstance(t, str) or not t.strip() for t in translations):
                        raise ValueError("Batch translations must be non-empty strings")

                    if len(translations) != len(texts_to_translate):
                        logger.warning(
                            f"Mismatch in translation batch size: expected {len(texts_to_translate)}, got {len(translations)}. Retrying individually."
                        )
                        raise ValueError("Mismatch in translation batch size")

                    for idx_in_non_empty, original_batch_idx in enumerate(non_empty_indices):
                        store_translation(batch[original_batch_idx], translations[idx_in_non_empty])

                    for idx, b in enumerate(batch):
                        if idx not in non_empty_indices:
                            store_translation(b, "")

                except ResourceLimitExceeded:
                    raise
                except Exception as e:
                    # Network failures happen before this parsing-only fallback.
                    logger.error(f"Batch processing failed at block {i}: {e}. Falling back to individual translation.")
                    for b in batch:
                        if b["text"]:
                            store_translation(b, await self.translate_text(b["text"], source_lang, target_lang))
                        else:
                            store_translation(b, "")

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
                    paragraphs.extend(TextSplitter(2500).split(p_clean, extract_srt=False))

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
            translated_size = 0
            for chunk in chunks:
                if chunk.strip():
                    translated_chunk = await self.translate_text(chunk, source_lang, target_lang)
                    translated_size += len(translated_chunk) + (2 if translated_paragraphs else 0)
                    if translated_size > ResourceLimits.from_env().max_text_chars:
                        raise ResourceLimitExceeded("Translated text exceeds MAX_TEXT_CHARS")
                    translated_paragraphs.append(translated_chunk)
                    await asyncio.sleep(1.0)
                else:
                    translated_paragraphs.append("")

            translated_content = "\n\n".join(translated_paragraphs)

        # Write translated file atomically to prevent corrupted or truncated files
        check_text(translated_content)
        save_text_atomic(output_path, translated_content)

        logger.info(f"Translated file written to {output_path}")
        return output_path
