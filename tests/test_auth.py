import json
import os
from unittest.mock import Mock

from fastapi import HTTPException, Request, Response
import pytest

from src.core.auth import hash_password, load_credentials, save_credentials, verify_password
from src import web


@pytest.fixture(autouse=True)
def isolated_login_limits(monkeypatch):
    monkeypatch.setattr(web, 'login_limiter', web.LoginLimiter())


def test_password_hash_is_salted_and_supports_unicode():
    password = 'Zażółć gęślą jaźń!'
    first = hash_password(password)
    assert first != hash_password(password)
    assert password not in first
    assert verify_password(password, first)
    assert not verify_password('incorrect', first)
    assert not verify_password(password, 'invalid')


def test_legacy_credentials_migrate_and_survive_restart(tmp_path):
    path = tmp_path / 'auth.json'
    path.write_text(json.dumps({'username': 'żółw', 'password': 'Zażółć!'}))
    username, encoded = load_credentials(path, 'ignored', 'ignored')
    saved = json.loads(path.read_text())
    assert username == 'żółw'
    assert 'password' not in saved
    assert verify_password('Zażółć!', saved['password_hash'])
    assert load_credentials(path, 'other', 'other') == (username, encoded)
    if os.name == 'posix':
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('content', ['{', '{}', '{"username":"admin","password_hash":"broken"}'])
def test_invalid_file_does_not_fall_back_to_environment(tmp_path, content):
    path = tmp_path / 'auth.json'
    path.write_text(content)
    with pytest.raises(RuntimeError, match='Cannot load'):
        load_credentials(path, 'admin', 'otherwise-valid')
    assert path.read_text() == content


def test_failed_migration_preserves_legacy_file(tmp_path, monkeypatch):
    path = tmp_path / 'auth.json'
    original = json.dumps({'username': 'admin', 'password': 'test-password'})
    path.write_text(original)
    monkeypatch.setattr('src.core.auth.save_credentials', Mock(side_effect=OSError('write failed')))
    with pytest.raises(OSError):
        load_credentials(path, 'ignored', 'ignored')
    assert path.read_text() == original


def test_atomic_write_failure_keeps_previous_file(tmp_path, monkeypatch):
    path = tmp_path / 'auth.json'
    path.write_text('previous')
    monkeypatch.setattr('pathlib.Path.replace', Mock(side_effect=OSError('replace failed')))
    with pytest.raises(OSError):
        save_credentials(path, 'admin', hash_password('new-password'))
    assert path.read_text() == 'previous'
    assert list(tmp_path.iterdir()) == [path]


def test_unicode_login_and_password_change(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'AUTH_FILE', tmp_path / 'auth.json')
    monkeypatch.setattr(web, 'APP_USERNAME', 'żółw')
    monkeypatch.setattr(web, 'APP_PASSWORD_HASH', hash_password('stare-hasło'))
    monkeypatch.setattr(web, 'active_sessions', {})
    web.login(web.LoginRequest(username='żółw', password='stare-hasło'), Response(), Request({'type': 'http', 'headers': []}))
    web.change_password(web.ChangePasswordRequest(current_password='stare-hasło', new_password='nowe-hasło'))
    web.login(web.LoginRequest(username='żółw', password='nowe-hasło'), Response(), Request({'type': 'http', 'headers': []}))
    with pytest.raises(HTTPException) as error:
        web.login(web.LoginRequest(username='żółw', password='stare-hasło'), Response(), Request({'type': 'http', 'headers': []}))
    assert error.value.status_code == 401
    assert 'password' not in json.loads(web.AUTH_FILE.read_text())


def test_failed_password_change_keeps_active_hash(monkeypatch):
    original = hash_password('original-password')
    monkeypatch.setattr(web, 'APP_PASSWORD_HASH', original)
    monkeypatch.setattr(web, 'save_credentials', Mock(side_effect=OSError('write failed')))
    with pytest.raises(HTTPException) as error:
        web.change_password(web.ChangePasswordRequest(current_password='original-password', new_password='new-password'))
    assert error.value.status_code == 500
    assert web.APP_PASSWORD_HASH == original


def test_hashed_file_permissions_are_restricted(tmp_path):
    if os.name != 'posix':
        pytest.skip('POSIX permissions')
    path = tmp_path / 'auth.json'
    save_credentials(path, 'admin', hash_password('test-password'))
    path.chmod(0o775)
    load_credentials(path, 'ignored', 'ignored')
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('hashed', [False, True])
def test_persisted_default_password_cannot_bypass_startup_check(tmp_path, hashed):
    path = tmp_path / 'auth.json'
    field = 'password_hash' if hashed else 'password'
    value = hash_password('admin') if hashed else 'admin'
    path.write_text(json.dumps({'username': 'custom-user', field: value}))
    with pytest.raises(RuntimeError, match='Unsafe WebUI credentials'):
        load_credentials(path, 'admin', 'otherwise-valid')
