"""Resource budgets shared by input parsers and the WebUI."""
from dataclasses import dataclass, fields
import os


class ResourceLimitExceeded(ValueError):
    pass


@dataclass(frozen=True)
class ResourceLimits:
    max_request_bytes: int = 32 * 1024 * 1024
    max_json_request_bytes: int = 64 * 1024
    request_body_timeout_seconds: int = 120
    request_body_idle_timeout_seconds: int = 15
    max_text_upload_bytes: int = 10 * 1024 * 1024
    max_voice_upload_bytes: int = 20 * 1024 * 1024
    max_voice_seconds: int = 30
    max_voice_process_memory_bytes: int = 512 * 1024 * 1024
    max_text_chars: int = 2_000_000
    max_epub_bytes: int = 64 * 1024 * 1024
    max_epub_entry_bytes: int = 8 * 1024 * 1024
    max_epub_entries: int = 10_000
    max_epub_xml_depth: int = 64
    max_epub_xml_elements: int = 10_000
    max_running_jobs: int = 2
    max_queued_jobs: int = 2

    @classmethod
    def from_env(cls):
        values = {}
        for field in fields(cls):
            name = field.name.upper()
            try:
                value = int(os.getenv(name, str(field.default)))
            except ValueError:
                raise ValueError(f"{name} must be an integer") from None
            if value < (0 if field.name == "max_queued_jobs" else 1):
                raise ValueError(f"{name} has an invalid limit")
            values[field.name] = value
        return cls(**values)


def check_text(text: str):
    if len(text) > ResourceLimits.from_env().max_text_chars:
        raise ResourceLimitExceeded("Text exceeds MAX_TEXT_CHARS")
    return text
