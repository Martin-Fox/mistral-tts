import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

from textual.widgets import Select
from src.tui import BooksmithTUI


@pytest.mark.anyio
async def test_tui_initial_translation_model_selection():
    """Verify TUI initializes translation-model-select with get_translation_model value."""
    with patch("src.tui.get_translation_model", return_value="mistral-large-latest"):
        app = BooksmithTUI()
        async with app.run_test():
            select = app.query_one("#translation-model-select", Select)
            assert select.value == "mistral-large-latest"


@pytest.mark.anyio
async def test_tui_initial_translation_model_fallback():
    """Verify TUI falls back to default if configured model is unknown/invalid."""
    with patch("src.tui.get_translation_model", return_value="unknown-model-xyz"):
        app = BooksmithTUI()
        async with app.run_test():
            select = app.query_one("#translation-model-select", Select)
            assert select.value == "ministral-8b-latest"


@pytest.mark.anyio
async def test_tui_select_changed_saves_model():
    """Verify changing translation-model-select calls save_translation_model."""
    with patch("src.tui.get_translation_model", return_value="ministral-8b-latest"), \
         patch("src.tui.save_translation_model") as mock_save:
        app = BooksmithTUI()
        async with app.run_test() as pilot:
            select = app.query_one("#translation-model-select", Select)
            select.value = "mistral-small-latest"
            await pilot.pause()

            mock_save.assert_called_with("mistral-small-latest")


@pytest.mark.anyio
async def test_tui_process_book_passes_translation_model(tmp_path, monkeypatch):
    """Verify process_book passes translation_model to MistralTTSClient when target_lang is specified."""
    monkeypatch.chdir(tmp_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        text_file = Path(tmpdir) / "sample.txt"
        text_file.write_text("Hello world", encoding="utf-8")
        out_file = Path(tmpdir) / "output.mp3"

        app = BooksmithTUI()
        app.log_message = MagicMock()
        app.query_one = MagicMock()

        with patch("src.tui.MistralTTSClient") as mock_client_cls, \
             patch("src.tui.get_tts_client") as mock_get_tts, \
             patch("src.tui.AudioCompiler"), \
             patch("src.tui.TextSplitter") as mock_splitter:
            
            mock_tts = MagicMock()
            mock_tts.model = 'voxtral-mini-tts-2603'
            async def generate(text, path):
                path.write_bytes(b'valid fake audio' * 20)
            mock_tts.generate_audio = AsyncMock(side_effect=generate)
            mock_get_tts.return_value = mock_tts

            mock_trans_client = MagicMock()
            mock_trans_client.translate_file = AsyncMock(return_value=text_file)
            mock_client_cls.return_value = mock_trans_client

            mock_splitter.return_value.split.return_value = ["Hello world"]
            mock_splitter.return_value.max_chars = 1000

            await app.process_book(
                text_path=str(text_file),
                voice_path="",
                voice_id="en_paul_neutral",
                output_path=str(out_file),
                api_key="test_api_key",
                source_lang="English",
                target_lang="Spanish",
                engine="mistral",
                translation_model="mistral-large-latest"
            )

            mock_client_cls.assert_called_once_with(
                api_key="test_api_key",
                translation_model="mistral-large-latest"
            )
            assert not any(str(call.args[0]).startswith('Error:') for call in app.log_message.call_args_list)
