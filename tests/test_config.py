import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from src.core.config import (
    DEFAULT_TRANSLATION_MODEL,
    get_env_path,
    get_translation_model,
    save_translation_model,
)


def test_get_translation_model_default(monkeypatch):
    """When MISTRAL_TRANSLATION_MODEL is not set and .env is missing/empty, returns default model."""
    monkeypatch.delenv("MISTRAL_TRANSLATION_MODEL", raising=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        with patch("src.core.config.get_env_path", return_value=fake_env):
            model = get_translation_model()
            assert model == DEFAULT_TRANSLATION_MODEL
            assert model == "ministral-8b-latest"


def test_get_translation_model_from_env_var(monkeypatch):
    """When MISTRAL_TRANSLATION_MODEL is present in os.environ, returns its value."""
    monkeypatch.setenv("MISTRAL_TRANSLATION_MODEL", "mistral-large-latest")
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        with patch("src.core.config.get_env_path", return_value=fake_env):
            assert get_translation_model() == "mistral-large-latest"


def test_get_translation_model_from_dotenv_file(monkeypatch):
    """When MISTRAL_TRANSLATION_MODEL is defined in .env file, load_dotenv loads it."""
    monkeypatch.delenv("MISTRAL_TRANSLATION_MODEL", raising=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        fake_env.write_text("MISTRAL_TRANSLATION_MODEL=mistral-small-latest\n", encoding="utf-8")
        with patch("src.core.config.get_env_path", return_value=fake_env):
            assert get_translation_model() == "mistral-small-latest"


def test_get_translation_model_empty_env_returns_default(monkeypatch):
    """When MISTRAL_TRANSLATION_MODEL is empty in os.environ, fallback to default."""
    monkeypatch.setenv("MISTRAL_TRANSLATION_MODEL", "")
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        with patch("src.core.config.get_env_path", return_value=fake_env):
            assert get_translation_model() == DEFAULT_TRANSLATION_MODEL


def test_save_translation_model_creates_file_and_updates_env(monkeypatch):
    """Saving translation model creates .env if missing and sets os.environ."""
    monkeypatch.delenv("MISTRAL_TRANSLATION_MODEL", raising=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        assert not fake_env.exists()

        with patch("src.core.config.get_env_path", return_value=fake_env):
            save_translation_model("mistral-medium-latest")

            assert fake_env.exists()
            content = fake_env.read_text(encoding="utf-8")
            assert "MISTRAL_TRANSLATION_MODEL=mistral-medium-latest" in content
            assert os.environ.get("MISTRAL_TRANSLATION_MODEL") == "mistral-medium-latest"
            assert get_translation_model() == "mistral-medium-latest"


def test_save_translation_model_preserves_existing_env_variables(monkeypatch):
    """Saving preserves existing environment variables in .env without overwriting them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        fake_env.write_text(
            "EXISTING_KEY=secret_value\nANOTHER_VAR=123\nMISTRAL_TRANSLATION_MODEL=old-model\n",
            encoding="utf-8"
        )

        with patch("src.core.config.get_env_path", return_value=fake_env):
            save_translation_model("mistral-large-latest")

            content = fake_env.read_text(encoding="utf-8")
            assert "EXISTING_KEY=secret_value" in content
            assert "ANOTHER_VAR=123" in content
            assert "MISTRAL_TRANSLATION_MODEL=mistral-large-latest" in content
            assert "old-model" not in content


def test_save_translation_model_strips_whitespace(monkeypatch):
    """Whitespace around model name is trimmed when saving."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_env = Path(tmpdir) / ".env"
        with patch("src.core.config.get_env_path", return_value=fake_env):
            save_translation_model("   ministral-3b-latest   ")
            assert os.environ.get("MISTRAL_TRANSLATION_MODEL") == "ministral-3b-latest"
            content = fake_env.read_text(encoding="utf-8")
            assert "MISTRAL_TRANSLATION_MODEL=ministral-3b-latest" in content


@pytest.mark.parametrize("invalid_input", [
    None,
    "",
    123,
    ["ministral-8b-latest"],
    {"model": "ministral-8b-latest"},
])
def test_save_translation_model_invalid_inputs_raise_error(invalid_input):
    """Non-string and empty inputs must raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        save_translation_model(invalid_input)
    assert "model_name must be a non-empty string" in str(exc_info.value)


def test_save_translation_model_whitespace_only_raises_error():
    """Whitespace-only model name raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        save_translation_model("   ")
    assert "model_name cannot be empty or whitespace only" in str(exc_info.value)


@pytest.mark.parametrize("invalid_format_input", [
    "ministral\n-8b-latest",
    "ministral\r-8b-latest",
    "ministral\r\nEVIL=1",
    "model;rm -rf /",
    "model$TEST",
    "model`id`",
    "model&calc",
    "model<script>",
    "model\x00null",
    "a" * 101,
])
def test_save_translation_model_invalid_format_raises_error(invalid_format_input):
    """Control characters, injection payloads, and invalid characters raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        save_translation_model(invalid_format_input)
    assert "Invalid model name format. Only alphanumeric characters, dashes, underscores, dots, and colons are allowed." in str(exc_info.value)


def test_get_env_path():
    """get_env_path returns a Path object pointing to .env."""
    path = get_env_path()
    assert isinstance(path, Path)
    assert path.name == ".env"
