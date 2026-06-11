import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import json
import tempfile
from src.api.mistral_client import MistralTTSClient

@pytest.mark.anyio
async def test_translate_text():
    # Setup client mock
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()
    
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Hola Mundo"
    mock_response.choices = [mock_choice]
    
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    res = await client.translate_text("Hello World", "English", "Spanish")
    
    assert res == "Hola Mundo"
    client.client.chat.complete_async.assert_called_once()
    call_kwargs = client.client.chat.complete_async.call_args[1]
    assert call_kwargs["model"] == "mistral-large-latest"
    assert call_kwargs["messages"][0]["content"].strip().endswith("Hello World")


@pytest.mark.anyio
async def test_translate_file_txt():
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()
    
    # Mock text translation response
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Hola. Esta es una prueba."
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "test.txt"
        input_file.write_text("Hello. This is a test.", encoding="utf-8")
        
        # We need to patch the save path to be inside tmpdir or mock translate_file's output path.
        # Let's patch Path("storage/translations") to return a path inside tmpdir.
        with patch("src.api.mistral_client.Path") as mock_path:
            # We want mock_path("storage/translations") to return a mock directory in our temp dir
            mock_translations_dir = MagicMock()
            mock_translations_dir.exists.return_value = True
            
            # Setup mock behavior
            def path_side_effect(*args):
                if len(args) == 1 and args[0] == "storage/translations":
                    return Path(tmpdir)
                return Path(*args)
                
            mock_path.side_effect = path_side_effect
            
            out_file = await client.translate_file(input_file, "English", "Spanish")
            
            assert out_file.exists()
            assert out_file.suffix == ".txt"
            content = out_file.read_text(encoding="utf-8")
            assert "Hola. Esta es una prueba." in content


@pytest.mark.anyio
async def test_translate_file_srt():
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()
    
    # Mock JSON response for srt translation
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "translations": [
            "Hola, ¿cómo estás?",
            "¡Estoy genial, gracias!"
        ]
    })
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    srt_content = """1
00:00:01,000 --> 00:00:04,000
Hello, how are you?

2
00:00:05,000 --> 00:00:08,000
I am doing great, thank you!
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "test.srt"
        input_file.write_text(srt_content, encoding="utf-8")
        
        with patch("src.api.mistral_client.Path") as mock_path:
            def path_side_effect(*args):
                if len(args) == 1 and args[0] == "storage/translations":
                    return Path(tmpdir)
                return Path(*args)
                
            mock_path.side_effect = path_side_effect
            
            out_file = await client.translate_file(input_file, "English", "Spanish")
            
            assert out_file.exists()
            assert out_file.suffix == ".srt"
            content = out_file.read_text(encoding="utf-8")
            
            # Verify translation output structure and translated values
            assert "00:00:01,000 --> 00:00:04,000" in content
            assert "Hola, ¿cómo estás?" in content
            assert "00:00:05,000 --> 00:00:08,000" in content
            assert "¡Estoy genial, gracias!" in content
