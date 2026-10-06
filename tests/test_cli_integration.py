import pytest
from pathlib import Path
from src.cli import BooksmithCLI

@pytest.mark.anyio
async def test_cli_validation_openai_cloning(tmp_path):
    # Create a dummy voice file to ensure it exists
    dummy_voice = tmp_path / "sample.mp3"
    dummy_voice.write_bytes(b"dummy")
    
    text_path = tmp_path / "text.txt"
    text_path.write_text("Hello")
    output_path = tmp_path / "output.mp3"
    
    cli = BooksmithCLI(api_key="mistral-key")
    with pytest.raises(ValueError) as excinfo:
        await cli.run(
            text_path=text_path,
            voice_path=dummy_voice,
            output_path=output_path,
            engine="openai",
            openai_key="openai-key"
        )
    assert "OpenAI TTS does not support voice cloning" in str(excinfo.value)

@pytest.mark.anyio
async def test_cli_validation_missing_key(tmp_path):
    text_path = tmp_path / "text.txt"
    text_path.write_text("Hello")
    output_path = tmp_path / "output.mp3"
    
    cli = BooksmithCLI(api_key="mistral-key")
    with pytest.raises(ValueError):
        await cli.run(
            text_path=text_path,
            voice_path=Path("alloy"),
            output_path=output_path,
            engine="openai",
            openai_key=None
        )


@pytest.mark.anyio
async def test_cli_pre_compilation_invalid_chunk_raises_runtime_error(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    text_path = tmp_path / "text.txt"
    text_path.write_text("Sentence one. Sentence two.")
    output_path = tmp_path / "output.mp3"

    cli = BooksmithCLI(api_key="mistral-key")
    cli.cache_dir = tmp_path / "cache"
    cli.cache_dir.mkdir(parents=True, exist_ok=True)

    with patch("src.cli.get_tts_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        # Mock generate_audio to create a file smaller than 100 bytes
        async def fake_generate(text, path):
            Path(path).write_bytes(b"small")
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate)
        mock_get_client.return_value = mock_client

        with pytest.raises(RuntimeError, match="Missing or invalid chunk audio file before compilation"):
            await cli.run(
                text_path=text_path,
                voice_path=Path(""),
                output_path=output_path,
                engine="mistral"
            )

