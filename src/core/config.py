import os
import re
from pathlib import Path
from dotenv import find_dotenv, load_dotenv, set_key

DEFAULT_TRANSLATION_MODEL = "ministral-8b-latest"
MODEL_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.:]+$")


def _restrict_env_permissions(env_path: Path) -> None:
    """API keys and APP_PASSWORD live in .env; keep the file owner-only on POSIX."""
    if os.name == "posix":
        try:
            env_path.chmod(0o600)
        except OSError:
            pass


def load_environment():
    """Keep ordinary dotenv discovery; allow an explicit file for isolated runs."""
    explicit = os.getenv('BOOKSMITH_ENV_FILE')
    env_file = explicit or find_dotenv(usecwd=True)
    if env_file:
        env_path = Path(env_file)
        if env_path.exists() and not env_path.is_symlink():
            _restrict_env_permissions(env_path)
    return load_dotenv(dotenv_path=explicit or None)

def get_env_path() -> Path:
    """
    Uses BOOKSMITH_ENV_FILE when set, otherwise searches cwd and its parents.

    Returns:
        Path: Path object pointing to the discovered .env file or Path(".env") as fallback.
    """
    explicit = os.getenv('BOOKSMITH_ENV_FILE')
    if explicit:
        return Path(explicit)
    env_file = find_dotenv(usecwd=True)
    if env_file:
        return Path(env_file)
    return Path(".env")

def get_translation_model() -> str:
    """
    Reads MISTRAL_TRANSLATION_MODEL from os.getenv or the local .env file.

    Returns:
        str: Model identifier string (defaults to 'ministral-8b-latest' if not configured).
    """
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    return os.getenv("MISTRAL_TRANSLATION_MODEL") or DEFAULT_TRANSLATION_MODEL

def save_translation_model(model_name: str) -> None:
    """
    Safely updates or creates MISTRAL_TRANSLATION_MODEL in the .env file and active environment.

    Args:
        model_name: Name of the Mistral model (e.g., 'ministral-8b-latest').

    Raises:
        ValueError: If model_name is not a non-empty string.
    """
    if not model_name or not isinstance(model_name, str):
        raise ValueError("model_name must be a non-empty string")

    clean_model = model_name.strip()
    if not clean_model:
        raise ValueError("model_name cannot be empty or whitespace only")

    if (
        len(clean_model) > 100
        or any(c in clean_model for c in ("\n", "\r", "\x00"))
        or not MODEL_NAME_REGEX.match(clean_model)
    ):
        raise ValueError("Invalid model name format. Only alphanumeric characters, dashes, underscores, dots, and colons are allowed.")

    env_path = get_env_path()

    if not env_path.exists():
        env_path.touch()

    set_key(
        dotenv_path=str(env_path),
        key_to_set="MISTRAL_TRANSLATION_MODEL",
        value_to_set=clean_model,
        quote_mode="never"
    )
    _restrict_env_permissions(env_path)
    os.environ["MISTRAL_TRANSLATION_MODEL"] = clean_model
