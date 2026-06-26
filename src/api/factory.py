from src.api.base_client import BaseTTSClient

def get_tts_client(engine: str, api_key: str) -> BaseTTSClient:
    """
    Factory function to retrieve a TTS client for the specified engine.
    """
    engine_normalized = engine.lower().strip()
    if engine_normalized == "mistral":
        from src.api.mistral_client import MistralTTSClient
        return MistralTTSClient(api_key)
    elif engine_normalized == "openai":
        from src.api.openai_client import OpenAITTSClient
        return OpenAITTSClient(api_key)
    else:
        raise ValueError(f"Unknown TTS engine: {engine}")
