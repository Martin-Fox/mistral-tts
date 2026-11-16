"""Password hashing and atomic credential persistence (no external dependencies)."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile


ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def validate_hash(encoded: str) -> tuple[int, bytes, bytes]:
    algorithm, iterations, salt, digest = encoded.split("$")
    rounds = int(iterations)
    salt_bytes, digest_bytes = bytes.fromhex(salt), bytes.fromhex(digest)
    if (
        algorithm != "pbkdf2_sha256"
        or rounds != ITERATIONS
        or len(salt_bytes) != 16
        or len(digest_bytes) != 32
    ):
        raise ValueError("Invalid password hash")
    return rounds, salt_bytes, digest_bytes


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        rounds, salt, expected = validate_hash(encoded)
    except (ValueError, TypeError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def save_credentials(path: Path, username: str, password_hash: str) -> None:
    """Publish only a complete file; mkstemp creates it with owner-only access."""
    fd, temporary = tempfile.mkstemp(prefix=".auth-", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"username": username, "password_hash": password_hash}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def load_credentials(path: Path, username: str, password: str) -> tuple[str, str]:
    """Migrate legacy files; persisted credentials take precedence over environment."""
    encoded = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            username = data["username"]
            if "password_hash" in data:
                encoded = data["password_hash"]
                validate_hash(encoded)
                password = None
            else:
                password = data["password"]
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            raise RuntimeError("Cannot load storage/auth.json; repair the credentials file before restarting.") from None

    if (
        not isinstance(username, str) or not username.strip()
        or (encoded is None and (
            not isinstance(password, str) or not password.strip()
            or password.strip() == "admin"
        ))
        or (encoded is not None and verify_password("admin", encoded))
    ):
        raise RuntimeError(
            "Unsafe WebUI credentials: configure a non-empty APP_USERNAME and "
            "APP_PASSWORD other than 'admin', or repair storage/auth.json "
            "if it exists (it takes precedence)."
        )
    if encoded is None:
        encoded = hash_password(password)
        if path.exists():
            save_credentials(path, username, encoded)
    elif os.name == "posix":
        path.chmod(0o600)
    return username, encoded
