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


@pytest.mark.anyio
async def test_translate_text_length_truncation_warning(caplog):
    import logging
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Truncated text..."
    mock_choice.finish_reason = "length"
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="Mistral translation exceeded token output capacity \\(finish_reason='length'\\)"):
            await client.translate_text("Long text", "English", "Spanish", retry_count=1)

    assert any("length" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_translate_file_splits_long_paragraphs(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    # Return translated version of each chunk
    async def fake_complete(*args, **kwargs):
        messages = kwargs.get("messages", [])
        content = messages[0]["content"]
        resp = MagicMock()
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message.content = f"TRANS[{len(content)}]"
        resp.choices = [choice]
        return resp

    client.client.chat.complete_async = AsyncMock(side_effect=fake_complete)

    # Create a long paragraph > 3000 chars with sentences
    long_sentences = ["This is a distinct test sentence for translation. " for _ in range(80)]
    long_para = "".join(long_sentences)
    assert len(long_para) > 3000

    input_file = tmp_path / "long_input.txt"
    input_file.write_text(long_para, encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        out_file = await client.translate_file(input_file, "English", "Spanish")

        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "TRANS[" in content
        # Ensure complete_async was called more than once due to paragraph splitting
        assert client.client.chat.complete_async.call_count >= 2


@pytest.mark.anyio
async def test_translate_file_stem_preservation_and_naming(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = "Texto traducido."
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    input_file = tmp_path / "wtfs_s02e02.txt"
    input_file.write_text("Original content.", encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        # 1. Default naming with single word target lang
        out_file1 = await client.translate_file(input_file, "English", "Spanish")
        assert out_file1.name == "wtfs_s02e02_translated_spanish.txt"
        assert out_file1.exists()

        # 2. Target lang with spaces
        out_file2 = await client.translate_file(input_file, "English", "Latin American Spanish")
        assert out_file2.name == "wtfs_s02e02_translated_latin_american_spanish.txt"
        assert out_file2.exists()

        # 3. Explicit custom output_filename override
        out_file3 = await client.translate_file(input_file, "English", "Spanish", output_filename="custom_episode.txt")
        assert out_file3.name == "custom_episode.txt"
        assert out_file3.exists()


@pytest.mark.anyio
async def test_translate_file_srt_non_standard_numbering_and_trailing_blocks(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    # Batch response mock
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = json.dumps({
        "translations": [
            "Línea de inicio.",
            "Línea final no estándar."
        ]
    })
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    srt_content = """10
00:00:01,000 --> 00:00:03,000
Opening line.

special_block_99
00:00:04,000 --> 00:00:07,000
Trailing non-standard line.


"""
    input_file = tmp_path / "wtfs_s02e02.srt"
    input_file.write_text(srt_content, encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        out_file = await client.translate_file(input_file, "English", "Spanish")
        assert out_file.name == "wtfs_s02e02_translated_spanish.srt"
        content = out_file.read_text(encoding="utf-8")
        assert "10" in content
        assert "Línea de inicio." in content
        assert "special_block_99" in content
        assert "Línea final no estándar." in content


@pytest.mark.anyio
async def test_translate_file_srt_length_truncation_warning(tmp_path, caplog):
    import logging
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "length"
    mock_choice.message.content = json.dumps({
        "translations": ["Línea traducida."]
    })
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    srt_content = """1
00:00:01,000 --> 00:00:03,000
Some text.
"""
    input_file = tmp_path / "test_warning.srt"
    input_file.write_text(srt_content, encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError, match="Mistral translation exceeded token output capacity \\(finish_reason='length'\\)"):
                with patch.object(
                    client,
                    "translate_text",
                    side_effect=RuntimeError("Mistral translation exceeded token output capacity (finish_reason='length')")
                ):
                    await client.translate_file(input_file, "English", "Spanish")

        assert any("length" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_translate_file_srt_length_fallback_to_individual_success(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    batch_resp = MagicMock()
    batch_choice = MagicMock()
    batch_choice.finish_reason = "length"
    batch_choice.message.content = json.dumps({"translations": ["Línea traducida."]})
    batch_resp.choices = [batch_choice]

    indiv_resp = MagicMock()
    indiv_choice = MagicMock()
    indiv_choice.finish_reason = "stop"
    indiv_choice.message.content = "Texto individual traducido."
    indiv_resp.choices = [indiv_choice]

    client.client.chat.complete_async = AsyncMock(side_effect=[batch_resp, indiv_resp])

    srt_content = """1
00:00:01,000 --> 00:00:03,000
Some text.
"""
    input_file = tmp_path / "test_fallback.srt"
    input_file.write_text(srt_content, encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        out_file = await client.translate_file(input_file, "English", "Spanish")
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "Texto individual traducido." in content


@pytest.mark.anyio
async def test_translate_file_path_traversal_prevention(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    input_file = tmp_path / "test.txt"
    input_file.write_text("Hello", encoding="utf-8")

    with pytest.raises(ValueError, match="Path traversal detected"):
        await client.translate_file(input_file, "English", "Spanish", output_filename="../../etc/passwd")


@pytest.mark.anyio
async def test_translate_file_splits_long_paragraphs_with_trailing_unpunctuated_text(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    captured_chunks = []
    async def fake_complete(*args, **kwargs):
        messages = kwargs.get("messages", [])
        content = messages[0]["content"]
        captured_chunks.append(content)
        resp = MagicMock()
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message.content = "Traducido"
        resp.choices = [choice]
        return resp

    client.client.chat.complete_async = AsyncMock(side_effect=fake_complete)

    # Paragraph > 2500 chars ending with trailing unpunctuated text
    sentences = ["A sentence that takes up some character space here. " for _ in range(60)]
    trailing_unpunctuated = "Trailing sentence without any ending period"
    full_text = "".join(sentences) + trailing_unpunctuated
    assert len(full_text) > 2500

    input_file = tmp_path / "trailing_long.txt"
    input_file.write_text(full_text, encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        out_file = await client.translate_file(input_file, "English", "Spanish")
        assert out_file.exists()
        # Verify that trailing unpunctuated text was passed into one of the translation chunks
        assert any(trailing_unpunctuated in chunk for chunk in captured_chunks)


@pytest.mark.anyio
async def test_translate_file_txt_length_truncation_raises_runtime_error(tmp_path, caplog):
    import logging
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "length"
    mock_choice.message.content = "Truncated text..."
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    input_file = tmp_path / "input_truncated.txt"
    input_file.write_text("Sentence to translate.", encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path, \
         patch("src.api.mistral_client.asyncio.sleep"):
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError, match="Mistral translation exceeded token output capacity \\(finish_reason='length'\\)"):
                await client.translate_file(input_file, "English", "Spanish")

        assert any("length" in r.message.lower() for r in caplog.records)
        # Ensure no output file or temporary file was leaked
        assert not (tmp_path / "input_truncated_translated_spanish.txt").exists()
        assert not (tmp_path / "input_truncated_translated_spanish.txt.tmp").exists()


@pytest.mark.anyio
async def test_translate_file_target_lang_path_traversal_sanitized(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    client.client = MagicMock()

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = "Traducido"
    mock_response.choices = [mock_choice]
    client.client.chat.complete_async = AsyncMock(return_value=mock_response)

    input_file = tmp_path / "doc.txt"
    input_file.write_text("Hello", encoding="utf-8")

    with patch("src.api.mistral_client.Path") as mock_path:
        def path_side_effect(*args):
            if len(args) == 1 and args[0] == "storage/translations":
                return tmp_path
            return Path(*args)
        mock_path.side_effect = path_side_effect

        # Attempt directory traversal in target_lang: ../../evil
        out_file = await client.translate_file(input_file, "English", "../../evil")
        assert out_file.exists()
        # Verify traversal slashes/dots are sanitized and file is securely contained in translations dir
        assert out_file.parent == tmp_path
        assert ".." not in out_file.name
        assert out_file.name == "doc_translated_______evil.txt"


@pytest.mark.anyio
async def test_translate_file_absolute_path_traversal_rejected(tmp_path):
    client = MistralTTSClient(api_key="dummy_key")
    input_file = tmp_path / "doc.txt"
    input_file.write_text("Hello", encoding="utf-8")

    # Providing an absolute path as output_filename should be rejected
    with pytest.raises(ValueError, match="Path traversal detected"):
        await client.translate_file(input_file, "English", "Spanish", output_filename="/etc/shadow")







