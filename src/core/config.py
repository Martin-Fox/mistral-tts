import os
import re
from pathlib import Path
from dotenv import find_dotenv, load_dotenv, set_key

DEFAULT_TRANSLATION_MODEL = "ministral-8b-latest"
MODEL_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.:]+$")

def get_env_path() -> Path:
    """
    Locates the .env file in the current working directory or parent directories.

    Returns:
        Path: Path object pointing to the discovered .env file or Path(".env") as fallback.
    """
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
    os.environ["MISTRAL_TRANSLATION_MODEL"] = clean_model
