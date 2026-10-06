import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.api.mistral_client import MistralTTSClient

@pytest.mark.anyio
async def test_mistral_generate_audio_too_small(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.set_voice_id("en_paul_neutral")
    client.client = MagicMock()

    mock_resp = MagicMock()
    mock_resp.audio_data = None
    mock_resp.audio = b"small"
    client.client.audio.speech.complete_async = AsyncMock(return_value=mock_resp)

    out_file = tmp_path / "chunk_small.mp3"
    with pytest.raises(RuntimeError, match="too small"):
        await client.generate_audio("Hello", out_file, retry_count=1)

@pytest.mark.anyio
async def test_mistral_generate_audio_invalid_duration(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.set_voice_id("en_paul_neutral")
    client.client = MagicMock()

    mock_resp = MagicMock()
    mock_resp.audio_data = None
    mock_resp.audio = b"a" * 200
    client.client.audio.speech.complete_async = AsyncMock(return_value=mock_resp)

    out_file = tmp_path / "chunk_corrupt.mp3"
    # ffprobe will fail on raw 'a' * 200
    with pytest.raises(RuntimeError, match="verification failed"):
        await client.generate_audio("Hello", out_file, retry_count=1)

@pytest.mark.anyio
async def test_mistral_generate_audio_success(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.set_voice_id("en_paul_neutral")
    client.client = MagicMock()

    mock_resp = MagicMock()
    mock_resp.audio_data = None
    mock_resp.audio = b"a" * 200
    client.client.audio.speech.complete_async = AsyncMock(return_value=mock_resp)

    out_file = tmp_path / "chunk_ok.mp3"

    # Patch ffprobe subprocess run to return valid duration
    with patch("subprocess.run") as mock_sub:
        mock_proc = MagicMock()
        mock_proc.stdout = "2.5\n"
        mock_sub.return_value = mock_proc

        await client.generate_audio("Hello", out_file, retry_count=1)

    assert out_file.exists()
    assert out_file.read_bytes() == b"a" * 200
