import asyncio
from unittest.mock import Mock

import pytest

from src import web


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "admin"),
        ("custom-user", "admin"),
        ("admin", " admin "),
        ("admin", ""),
        ("admin", "   "),
        ("", "test-only-password"),
        ("   ", "test-only-password"),
        (None, "test-only-password"),
        ("admin", None),
    ],
)
def test_startup_rejects_unsafe_credentials(monkeypatch, tmp_path, username, password):
    monkeypatch.setattr(web, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(web, "APP_USERNAME", username)
    monkeypatch.setattr(web, "APP_PASSWORD", password)
    create_task = Mock()
    monkeypatch.setattr(web.asyncio, "create_task", create_task)

    with pytest.raises(RuntimeError, match="Unsafe WebUI credentials"):
        asyncio.run(web.startup_event())

    create_task.assert_not_called()


def test_startup_accepts_configured_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(web, "APP_PASSWORD_HASH", None)
    monkeypatch.setattr(web, "APP_USERNAME", "admin")
    monkeypatch.setattr(web, "APP_PASSWORD", "test-only-password")
    purger = Mock(return_value=object())
    create_task = Mock()
    monkeypatch.setattr(web, "task_purger_loop", purger)
    monkeypatch.setattr(web.asyncio, "create_task", create_task)

    asyncio.run(web.startup_event())

    purger.assert_called_once_with()
    create_task.assert_called_once_with(purger.return_value)
