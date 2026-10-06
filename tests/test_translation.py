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
    assert call_kwargs["model"] == client.translation_model
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


@pytest.mark.anyio
async def test_translate_file_epub():
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()
    
    # Mock text translation response
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Capítulo Uno: Hola Mundo."
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    from tests.test_epub import create_mock_epub
    chapters = [
        ("chapter1.xhtml", "<html><body><h1>Chapter One: Hello World.</h1></body></html>")
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "test.epub"
        create_mock_epub(input_file, chapters)
        
        with patch("src.api.mistral_client.Path") as mock_path:
            def path_side_effect(*args):
                if len(args) == 1 and args[0] == "storage/translations":
                    return Path(tmpdir)
                return Path(*args)
                
            mock_path.side_effect = path_side_effect
            
            out_file = await client.translate_file(input_file, "English", "Spanish")
            
            assert out_file.exists()
            assert out_file.suffix == ".txt"
            content = out_file.read_text(encoding="utf-8")
            assert "Capítulo Uno: Hola Mundo." in content



@pytest.mark.anyio
async def test_translate_file_mobi():
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()
    
    # Mock text translation response
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Capítulo Uno: Hola Mundo."
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    with tempfile.TemporaryDirectory() as tmpdir:
        mobi_file_path = Path(tmpdir) / "book.mobi"
        mobi_file_path.write_text("fake binary mobi content", encoding="utf-8")
        
        # Create a mock extracted html file
        extraction_dir = Path(tmpdir) / "extraction"
        extraction_dir.mkdir()
        extracted_html_path = extraction_dir / "mobi_content.html"
        extracted_html_path.write_text("<html><body><h1>Chapter One: Hello World.</h1></body></html>", encoding="utf-8")
        
        with patch("mobi.extract") as mock_extract, patch("src.api.mistral_client.Path") as mock_path:
            mock_extract.return_value = (str(extraction_dir), str(extracted_html_path))
            
            def path_side_effect(*args):
                if len(args) == 1 and args[0] == "storage/translations":
                    return Path(tmpdir)
                return Path(*args)
                
            mock_path.side_effect = path_side_effect
            
            out_file = await client.translate_file(mobi_file_path, "English", "Spanish")
            
            assert out_file.exists()
            assert out_file.suffix == ".txt"
            content = out_file.read_text(encoding="utf-8")
            assert "Capítulo Uno: Hola Mundo." in content


@pytest.mark.anyio
async def test_client_custom_translation_model():
    """Verify that MistralTTSClient accepts a custom translation_model and passes it to complete_async."""
    client = MistralTTSClient(api_key="dummy_key", translation_model="mistral-large-latest")
    assert client.translation_model == "mistral-large-latest"

    client.client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Bonjour"
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    res = await client.translate_text("Hello", "English", "French")
    assert res == "Bonjour"
    call_kwargs = client.client.chat.complete_async.call_args[1]
    assert call_kwargs["model"] == "mistral-large-latest"


def test_client_translation_model_fallback(monkeypatch):
    """Verify fallback hierarchy: explicit arg > env var > default."""
    # 1. Env var set
    monkeypatch.setenv("MISTRAL_TRANSLATION_MODEL", "mistral-small-latest")
    client_env = MistralTTSClient(api_key="dummy_key")
    assert client_env.translation_model == "mistral-small-latest"

    # 2. Explicit arg overrides env var
    client_override = MistralTTSClient(api_key="dummy_key", translation_model="ministral-3b-latest")
    assert client_override.translation_model == "ministral-3b-latest"

    # 3. Unset env var falls back to default ministral-8b-latest
    monkeypatch.delenv("MISTRAL_TRANSLATION_MODEL", raising=False)
    client_default = MistralTTSClient(api_key="dummy_key")
    assert client_default.translation_model == "ministral-8b-latest"




