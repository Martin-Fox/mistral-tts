import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from src.api.openai_client import OpenAITTSClient

@pytest.mark.anyio
async def test_openai_list_voices():
    client = OpenAITTSClient(api_key="dummy-key")
    voices = await client.list_voices()
    assert len(voices) == 6
    voice_ids = [v["id"] for v in voices]
    assert voice_ids == ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

@pytest.mark.anyio
async def test_openai_clone_voice_raises_error():
    client = OpenAITTSClient(api_key="dummy-key")
    with pytest.raises(NotImplementedError):
        await client.clone_voice(Path("dummy.mp3"))

@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
async def test_openai_generate_audio(mock_post, tmp_path):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.content = b"fake-audio-bytes"
    mock_post.return_value = mock_response

    client = OpenAITTSClient(api_key="dummy-key")
    out_path = tmp_path / "test_openai.mp3"
    
    await client.generate_audio("Hello", out_path)
    assert out_path.exists()
    assert out_path.read_bytes() == b"fake-audio-bytes"

@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
@patch("asyncio.sleep", return_value=None)  # Mock sleep to speed up the test
async def test_openai_generate_audio_retry_success(mock_sleep, mock_post, tmp_path):
    # Mock first call failing (status 500), second succeeding (status 200)
    mock_fail_response = AsyncMock()
    mock_fail_response.status_code = 500
    mock_fail_response.text = "Internal Server Error"
    
    mock_success_response = AsyncMock()
    mock_success_response.status_code = 200
    mock_success_response.content = b"retry-audio-bytes"
    
    mock_post.side_effect = [mock_fail_response, mock_success_response]
    
    client = OpenAITTSClient(api_key="dummy-key")
    out_path = tmp_path / "test_openai_retry.mp3"
    
    await client.generate_audio("Hello retry", out_path)
    assert out_path.exists()
    assert out_path.read_bytes() == b"retry-audio-bytes"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(1)  # 2^0 = 1 second backoff for first retry

@pytest.mark.anyio
@patch("httpx.AsyncClient.post")
@patch("asyncio.sleep", return_value=None)
async def test_openai_generate_audio_retry_failure(mock_sleep, mock_post, tmp_path):
    # Mock all 3 calls failing
    mock_fail_response = AsyncMock()
    mock_fail_response.status_code = 500
    mock_fail_response.text = "Internal Server Error"
    mock_post.return_value = mock_fail_response
    
    client = OpenAITTSClient(api_key="dummy-key")
    out_path = tmp_path / "test_openai_fail.mp3"
    
    with pytest.raises(ValueError, match="OpenAI TTS API Error"):
        await client.generate_audio("Hello fail", out_path, retry_count=3)
    
    assert not out_path.exists()
    assert mock_post.call_count == 3
    assert mock_sleep.call_count == 2  # Sleeps after attempt 1 (1s) and attempt 2 (2s)
