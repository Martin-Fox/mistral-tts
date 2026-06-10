import asyncio
import logging
import base64
from pathlib import Path
from typing import Optional
from mistralai.client import Mistral

logger = logging.getLogger(__name__)

class MistralTTSClient:
    """
    Wrapper for Mistral AI Voxtral API interaction, including voice cloning
    and asynchronous text-to-speech generation.
    """

    def __init__(self, api_key: str):
        self.client = Mistral(api_key=api_key.strip())
        self.model = "voxtral-mini-tts-2603"
        self.voice_sample_path: Optional[Path] = None
        self.voice_id: Optional[str] = None

    async def list_models(self) -> list:
        """Lists available models from the Mistral API."""
        try:
            response = await self.client.models.list_async()
            return [m.id for m in response.data]
        except Exception as e:
            logger.warning(f"Failed to fetch models from API: {e}")
            return []

    async def list_voices(self) -> list:
        """
        Lists available voices from the Mistral API.
        Returns a list of voice objects with id and name.
        """
        try:
            response = await self.client.audio.voices.list_async()
            return [{"id": v.id, "name": v.name} for v in response.data]
        except Exception as e:
            logger.warning(f"Failed to fetch voices from API: {e}")
            # Fallback to some common defaults if API fails or key is missing
            return [
                {"id": "paul", "name": "Paul (Male)"},
                {"id": "mistral-en-001", "name": "English Male (US)"},
                {"id": "mistral-en-002", "name": "English Female (US)"},
                {"id": "mistral-en-003", "name": "English Male (UK)"},
                {"id": "mistral-en-004", "name": "English Female (UK)"},
            ]

    def set_voice_id(self, voice_id: str):
        """Sets a default voice ID to use."""
        self.voice_id = voice_id
        self.voice_sample_path = None

    async def clone_voice(self, audio_path: Path) -> str:
        """
        Sets a reference voice sample for zero-shot cloning.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Voice sample not found at {audio_path}")
        
        logger.info(f"Setting reference voice from {audio_path}")
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
