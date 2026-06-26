from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union, List, Dict, Any

class BaseTTSClient(ABC):
    """
    Abstract base class for Text-to-Speech clients.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key

    @abstractmethod
    async def generate_audio(
        self,
        text: str,
        output_path: Union[str, Path],
        retry_count: int = 3
    ) -> None:
        """
        Generates audio for a given text chunk and saves it to output_path.
        """
        pass

    @abstractmethod
    async def list_voices(self, retry_count: int = 3) -> List[Dict[str, Any]]:
        """
        Lists available voices from the TTS API.
        """
        pass

    @abstractmethod
    async def clone_voice(self, audio_path: Union[str, Path]) -> str:
        """
        Sets or registers a reference voice sample for voice cloning.
        """
        pass
