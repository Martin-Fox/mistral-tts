import httpx
import logging
from src.api.retry import call_api, APIResponseError, validate_retry_settings
from pathlib import Path
from typing import Union, List, Dict, Any
from src.api.base_client import BaseTTSClient
from src.api.factory import DEFAULT_TTS_MODELS

logger = logging.getLogger(__name__)

class OpenAITTSClient(BaseTTSClient):
    """
    Client for OpenAI TTS API interaction.
    """
    def __init__(self, api_key: str):
        super().__init__(api_key)
        validate_retry_settings()
        self.api_url = "https://api.openai.com/v1/audio/speech"
        self.model = DEFAULT_TTS_MODELS["openai"]
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

        async def request():
            timeout, _, _ = validate_retry_settings()
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                if response.status_code != 200:
                    raise APIResponseError(response.status_code, response.headers, 'OpenAI TTS')
                return response

        response = await call_api(request, attempts=retry_count)
        output_path.write_bytes(response.content)
        if not output_path.exists() or output_path.stat().st_size <= 100:
            raise RuntimeError(f"Generated OpenAI audio file is missing or too small (<= 100 bytes): {output_path}")
        logger.info(f"Successfully generated OpenAI TTS audio for: {output_path}")

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
