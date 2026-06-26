from pathlib import Path
from typing import Union, List, Dict, Any
from src.api.base_client import BaseTTSClient

class OpenAITTSClient(BaseTTSClient):
    """
    Client for OpenAI TTS API interaction.
    """
    async def generate_audio(
        self,
        text: str,
        output_path: Union[str, Path],
        retry_count: int = 3
    ) -> None:
        """
        Generates audio using OpenAI TTS API.
        """
        pass

    async def list_voices(self, retry_count: int = 3) -> List[Dict[str, Any]]:
        """
        Lists available OpenAI voices.
        """
        return []

    async def clone_voice(self, audio_path: Union[str, Path]) -> str:
        """
        OpenAI does not support custom voice cloning natively in the standard TTS API,
        but we define it to conform to BaseTTSClient.
        """
        return ""
