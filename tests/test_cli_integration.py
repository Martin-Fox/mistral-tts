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
