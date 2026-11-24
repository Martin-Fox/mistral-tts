"""Desktop launcher network-binding warning regressions."""
import logging


def test_warn_on_cleartext_binding_remote_without_secure_cookie(monkeypatch, caplog):
    from src.desktop import warn_on_cleartext_binding
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    with caplog.at_level(logging.WARNING, logger="booksmith-desktop"):
        warn_on_cleartext_binding("0.0.0.0")
    assert "cleartext HTTP" in caplog.text


def test_warn_on_cleartext_binding_silent_when_secure_cookie(monkeypatch, caplog):
    from src.desktop import warn_on_cleartext_binding
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    with caplog.at_level(logging.WARNING, logger="booksmith-desktop"):
        warn_on_cleartext_binding("0.0.0.0")
    assert not caplog.text


def test_warn_on_cleartext_binding_silent_on_loopback(monkeypatch, caplog):
    from src.desktop import warn_on_cleartext_binding
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    with caplog.at_level(logging.WARNING, logger="booksmith-desktop"):
        warn_on_cleartext_binding("127.0.0.1")
        warn_on_cleartext_binding("localhost")
        warn_on_cleartext_binding("::1")
    assert not caplog.text
