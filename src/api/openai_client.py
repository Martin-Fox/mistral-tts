import httpx
import logging
import asyncio
from pathlib import Path
from typing import Union, List, Dict, Any
from src.api.base_client import BaseTTSClient

logger = logging.getLogger(__name__)

class OpenAITTSClient(BaseTTSClient):
    """
    Client for OpenAI TTS API interaction.
    """
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.api_url = "https://api.openai.com/v1/audio/speech"
        self.model = "tts-1"
        self.voice_id = "alloy"  # Default voice

    def set_voice_id(self, voice_id: str) -> None:
        """
        Sets the selected preset voice ID.
        """
        self.voice_id = voice_id.strip().lower()

    async def generate_audio(
        self,
        text: str,
        output_path: Union[str, Path],
        retry_count: int = 3
    ) -> None:
        """
        Generates audio using OpenAI TTS API.
        """
        output_path = Path(output_path)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice_id,
            "response_format": "mp3"
        }

        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(self.api_url, headers=headers, json=payload)
                    
                    if response.status_code == 200:
                        output_path.write_bytes(response.content)
                        logger.info(f"Successfully generated OpenAI TTS audio for: {output_path}")
                        return
                    else:
                        error_detail = response.text
                        logger.warning(
                            f"OpenAI API returned status {response.status_code} on attempt {attempt + 1}: {error_detail}"
                        )
                        raise ValueError(f"OpenAI TTS API Error: Status {response.status_code} - {error_detail}")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for OpenAI TTS chunk {output_path}: {e}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to generate OpenAI audio after {retry_count} attempts.")
                    raise

    async def list_voices(self, retry_count: int = 3) -> List[Dict[str, Any]]:
        """
        Lists available OpenAI voices.
        """
        return [
            {"id": "alloy", "name": "Alloy (Neutral)"},
            {"id": "echo", "name": "Echo (Balanced)"},
            {"id": "fable", "name": "Fable (Narrative)"},
            {"id": "onyx", "name": "Onyx (Deep/Male)"},
            {"id": "nova", "name": "Nova (Energetic/Female)"},
            {"id": "shimmer", "name": "Shimmer (Professional)"},
        ]

    async def clone_voice(self, audio_path: Union[str, Path]) -> str:
        """
        OpenAI does not support custom voice cloning natively in the standard TTS API,
        but we define it to conform to BaseTTSClient.
        """
        raise NotImplementedError("OpenAI TTS does not support zero-shot voice cloning.")
