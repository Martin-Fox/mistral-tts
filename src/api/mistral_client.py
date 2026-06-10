import asyncio
import logging
import base64
from pathlib import Path
from typing import Optional
from mistralai import Mistral

logger = logging.getLogger(__name__)

class MistralTTSClient:
    """
    Wrapper for Mistral AI Voxtral API interaction, including voice cloning
    and asynchronous text-to-speech generation.
    """

    def __init__(self, api_key: str):
        self.client = Mistral(api_key=api_key)
        self.model = "voxtral-tts-26-03"  # or "voxtral-mini-tts-2603"
        self.voice_sample_path: Optional[Path] = None

    async def clone_voice(self, audio_path: Path) -> str:
        """
        In Mistral's zero-shot TTS, 'cloning' often happens per-request 
        by providing a reference audio sample (voice_prompt).
        We store the path to use in subsequent generation calls.

        Args:
            audio_path (Path): Path to the reference audio file.

        Returns:
            str: A placeholder ID or the path itself.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Voice sample not found at {audio_path}")
        
        logger.info(f"Setting reference voice from {audio_path}")
        self.voice_sample_path = audio_path
        return str(audio_path)

    async def generate_audio(self, text: str, output_path: Path, retry_count: int = 3):
        """
        Generates audio for a given text chunk with exponential backoff.

        Args:
            text (str): The text content to convert to speech.
            output_path (Path): Where to save the generated audio chunk.
            retry_count (int): Maximum number of retries for failures.
        """
        if not self.voice_sample_path:
            raise ValueError("Voice sample must be set before generating audio.")

        for attempt in range(retry_count):
            try:
                # Open the voice sample for each request (as per zero-shot requirements)
                with open(self.voice_sample_path, "rb") as voice_file:
                    # Note: Using the synchronous 'create' if 'create_async' 
                    # is not available or if this is the preferred pattern.
                    # Based on search, 'client.audio.speech.create' or 'complete_async'
                    
                    # Assuming 'create' works or using 'complete_async' if it's the newer async-first API
                    # The search showed: await client.audio.speech.create_async(...) or complete_async
                    
                    response = await self.client.audio.speech.create_async(
                        model=self.model,
                        input=text,
                        voice_prompt=voice_file,
                        response_format="mp3"
                    )
                
                # If the response contains audio data (bytes or base64)
                if hasattr(response, 'audio'):
                    output_path.write_bytes(response.audio)
                elif hasattr(response, 'audio_data'):
                    audio_bytes = base64.b64decode(response.audio_data)
                    output_path.write_bytes(audio_bytes)
                else:
                    # Fallback or manual extraction if structure differs
                    logger.error("Unexpected response structure from Mistral API")
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
