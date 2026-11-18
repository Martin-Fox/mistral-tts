"""Canonical v2 identity shared by CLI, WebUI and TUI; excludes keys and file paths."""

import hashlib
import json
from pathlib import Path

from src.api.factory import DEFAULT_TTS_MODELS
from src.core.config import get_translation_model
from src.core.text_splitter import SPLITTER_VERSION


# Bump whenever reference preprocessing changes the audio sent to the provider.
VOICE_PREPROCESS_VERSION = 3


def hash_sample_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def get_cache_key(
    text: str,
    voice_preset: str | None,
    voice_manual_id: str | None,
    voice_bytes: bytes | None,
    source_lang: str | None,
    target_lang: str | None,
    translation_model: str | None = None,
    *,
    engine: str = "mistral",
    tts_model: str | None = None,
    voice_sample_hash: str | None = None,
    max_chars: int = 1000,
    processed_voice_bytes: bytes | None = None,
) -> str:
    engine = engine.strip().lower()
    if engine not in DEFAULT_TTS_MODELS:
        raise ValueError(f"Unknown TTS engine: {engine}")
    sample_hash = voice_sample_hash
    if voice_bytes is not None:
        sample_hash = hashlib.sha256(voice_bytes).hexdigest()
    if engine == "openai":
        # OpenAI ignores reference audio and normalizes preset names.
        voice = {"id": (voice_preset or voice_manual_id or "alloy").strip().lower()}
    elif sample_hash is not None:
        voice = {"sample_sha256": sample_hash, "processing_version": VOICE_PREPROCESS_VERSION}
        if isinstance(processed_voice_bytes, bytes):
            voice["processed_sha256"] = hashlib.sha256(processed_voice_bytes).hexdigest()
    else:
        voice = {"id": voice_preset or voice_manual_id or "en_paul_neutral"}
    identity = {
        "schema": 2,
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "tts": {"engine": engine, "model": tts_model or DEFAULT_TTS_MODELS[engine], "format": "mp3"},
        "voice": voice,
        "translation": {
            "source": source_lang or "English",
            "target": target_lang,
            "model": translation_model or get_translation_model(),
        } if target_lang else None,
        "splitter": {"version": SPLITTER_VERSION, "max_chars": max_chars},
    }
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "v2_" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
