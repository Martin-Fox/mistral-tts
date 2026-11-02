from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request, Response

from src import web
from src.core.auth import hash_password


@pytest.fixture
def sessions(monkeypatch):
    monkeypatch.setattr(web, 'active_sessions', {})
    monkeypatch.setattr(web, 'login_limiter', web.LoginLimiter())
    monkeypatch.setattr(web, 'SESSION_TTL_SECONDS', 60)
    monkeypatch.setattr(web, 'SESSION_COOKIE_SECURE', False)
    monkeypatch.setattr(web, 'APP_USERNAME', 'test-user')
    monkeypatch.setattr(web, 'APP_PASSWORD_HASH', hash_password('test-password'))
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr(web.time, 'monotonic', clock)
    return clock


def sign_in():
    response = Response()
    web.login(web.LoginRequest(username='test-user', password='test-password'), response, Request({'type': 'http', 'headers': []}))
    cookie = SimpleCookie(response.headers['set-cookie'])['session_id']
    return cookie, response


def request_for(token):
    return Request({'type': 'http', 'headers': [(b'cookie', f'session_id={token}'.encode())]})


def test_expiry_is_absolute_and_checked_by_auth_status(sessions):
    cookie, _ = sign_in()
    token = cookie.value
    sessions.return_value = 1059
    assert web.verify_session(token) == token
    assert web.get_auth_status(request_for(token))['authenticated'] is True
    sessions.return_value = 1060
    assert web.get_auth_status(request_for(token)) == {'authenticated': False}
    with pytest.raises(HTTPException) as error:
        web.verify_session(token)
    assert error.value.status_code == 401
    assert token not in web.active_sessions


def test_new_login_removes_expired_entries(sessions):
    old, _ = sign_in()
    sessions.return_value = 1060
    new, _ = sign_in()
    assert old.value not in web.active_sessions
    assert web.verify_session(new.value) == new.value


@pytest.mark.parametrize('secure', [False, True])
def test_cookie_flags_match_configuration(sessions, monkeypatch, secure):
    monkeypatch.setattr(web, 'SESSION_COOKIE_SECURE', secure)
    cookie, _ = sign_in()
    assert cookie['max-age'] == '60'
    assert cookie['httponly']
    assert cookie['samesite'] == 'lax'
    assert bool(cookie['secure']) is secure
    response = Response()
    web.logout(request_for(cookie.value), response)
    assert not web.session_is_valid(cookie.value)
    deleted = SimpleCookie(response.headers['set-cookie'])['session_id']
    assert deleted['max-age'] == '0'
    assert bool(deleted['secure']) is secure
    # Repeated logout is harmless.
    web.logout(request_for(cookie.value), Response())


def test_password_change_revokes_both_clients(sessions, monkeypatch, tmp_path):
    first, _ = sign_in()
    second, _ = sign_in()
    monkeypatch.setattr(web, 'AUTH_FILE', tmp_path / 'auth.json')
    web.change_password(web.ChangePasswordRequest(
        current_password='test-password', new_password='new-test-password'
    ), session=first.value)
    for cookie in (first, second):
        with pytest.raises(HTTPException) as error:
            web.verify_session(cookie.value)
        assert error.value.status_code == 401
    response = Response()
    web.login(web.LoginRequest(username='test-user', password='new-test-password'), response, Request({'type': 'http', 'headers': []}))
    assert web.active_sessions


def test_failed_password_write_does_not_revoke_sessions(sessions, monkeypatch):
    cookie, _ = sign_in()
    monkeypatch.setattr(web, 'save_credentials', Mock(side_effect=OSError('test failure')))
    with pytest.raises(HTTPException):
        web.change_password(web.ChangePasswordRequest(
            current_password='test-password', new_password='new-test-password'
        ), session=cookie.value)
    assert web.verify_session(cookie.value) == cookie.value


@pytest.mark.parametrize(('ttl', 'secure', 'workers'), [
    ('0', 'false', '1'), ('-1', 'false', '1'), ('bad', 'false', '1'),
    ('60', 'yes', '1'), ('60', 'false', '2'), ('60', 'false', 'bad'),
])
def test_invalid_configuration_fails_closed(monkeypatch, ttl, secure, workers):
    monkeypatch.setenv('SESSION_TTL_SECONDS', ttl)
    monkeypatch.setenv('SESSION_COOKIE_SECURE', secure)
    monkeypatch.setenv('WEB_CONCURRENCY', workers)
    with pytest.raises(RuntimeError):
        web.configure_sessions()


def test_configuration_and_defaults(monkeypatch, sessions):
    for name in ('SESSION_TTL_SECONDS', 'SESSION_COOKIE_SECURE', 'WEB_CONCURRENCY'):
        monkeypatch.delenv(name, raising=False)
    web.configure_sessions()
    assert web.SESSION_TTL_SECONDS == 28800
    assert web.SESSION_COOKIE_SECURE is False
    monkeypatch.setenv('SESSION_TTL_SECONDS', '120')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'true')
    web.configure_sessions()
    assert web.SESSION_TTL_SECONDS == 120
    assert web.SESSION_COOKIE_SECURE is True


@pytest.mark.parametrize('revoked', [False, True])
def test_progress_stream_stops_after_expiry_or_revocation(sessions, monkeypatch, revoked):
    import asyncio

    cookie, _ = sign_in()
    database = Mock()
    database.get_task.return_value = {
        'percentage': 10, 'status': 'Generating Audio', 'completed': False,
        'audio_file': None, 'error': None,
    }
    database.get_logs.return_value = []
    monkeypatch.setattr(web, 'db', database)
    monkeypatch.setattr(web.asyncio, 'sleep', AsyncMock())

    async def check():
        response = await web.get_progress('test-task', 0, session=cookie.value)
        stream = response.body_iterator
        assert 'Generating Audio' in await anext(stream)
        if revoked:
            web.active_sessions.clear()
        else:
            sessions.return_value = 1060
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(check())
