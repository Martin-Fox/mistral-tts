import pytest
from src.api.factory import get_tts_client
from src.api.base_client import BaseTTSClient
from src.api.mistral_client import MistralTTSClient
from src.api.openai_client import OpenAITTSClient

def test_get_tts_client_exists():
    assert get_tts_client is not None

def test_get_tts_client_unknown_engine():
    with pytest.raises(ValueError):
        get_tts_client("unknown_engine", "fake_api_key")

def test_get_tts_client_mistral():
    client = get_tts_client("mistral", "fake_key")
    assert isinstance(client, MistralTTSClient)
    assert isinstance(client, BaseTTSClient)

def test_get_tts_client_openai():
    client = get_tts_client("openai", "fake_key")
    assert isinstance(client, OpenAITTSClient)
    assert isinstance(client, BaseTTSClient)

def test_get_tts_client_case_insensitive_and_whitespace():
    client_mistral = get_tts_client("  MIsTraL  ", "fake_key")
    assert isinstance(client_mistral, MistralTTSClient)
    
    client_openai = get_tts_client("  OpEnAI  ", "fake_key")
    assert isinstance(client_openai, OpenAITTSClient)
