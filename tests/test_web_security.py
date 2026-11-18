import asyncio
import json
import time
import zipfile
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
import pytest

from src import web
from src.core.auth import hash_password, load_credentials, verify_password
from src.core.epub_parser import strip_namespaces
from src.core.resource_limits import ResourceLimitExceeded
from src.web_security import origin_identity
from test_epub import create_mock_epub


def http_scope(path, headers):
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': 'POST', 'path': path, 'raw_path': path.encode(), 'root_path': '',
            'scheme': 'http', 'query_string': b'', 'client': ('127.0.0.1', 12345),
            'server': ('test', 80), 'headers': [(b'host', b'test'), *headers]}


@pytest.mark.parametrize('path', ['/api/auth/login', '/api/auth/logout', '/api/auth/change-password',
                                 '/api/config', '/api/generate', '/api/resume/task-id'])
@pytest.mark.parametrize('origin', [None, 'null', 'http://evil.test', 'http://sub.test',
                                   'https://test', 'http://test:81', 'http://test@evil.test'])
def test_bad_origin_rejected_before_body_auth_or_admission(monkeypatch, path, origin):
    headers = [] if origin is None else [(b'origin', origin.encode())]
    # A bad Origin cannot be overridden by a custom header.
    if origin is not None:
        headers.append((b'x-requested-with', b'Booksmith'))
    receive, send, verify, controller = AsyncMock(), AsyncMock(), Mock(), Mock()
    monkeypatch.setattr(web, 'verify_password', verify)
    monkeypatch.setattr(web, 'job_controller', controller)
    asyncio.run(web.app(http_scope(path, headers), receive, send))
    assert send.await_args_list[0].args[0]['status'] == 403
    receive.assert_not_called()
    verify.assert_not_called()
    controller.admission.acquire.assert_not_called()


def test_duplicate_origin_headers_are_rejected():
    scope = http_scope('/api/auth/login', [(b'origin', b'http://test'), (b'origin', b'http://evil.test')])
    receive, send = AsyncMock(), AsyncMock()
    asyncio.run(web.app(scope, receive, send))
    assert send.await_args_list[0].args[0]['status'] == 403
    receive.assert_not_called()


@pytest.mark.parametrize('base,origin', [('http://testserver', 'http://testserver:80'),
                                      ('https://testserver', 'https://testserver:443'),
                                      ('http://[::1]:8091', 'http://[::1]:8091')])
def test_browser_same_origin_login_with_default_ports_and_ipv6(base, origin):
    # Starlette's HTTPX TestClient splits IPv6 netloc incorrectly. Exercise the
    # actual ASGI Host header instead; origin matching must use this authority.
    client = (TestClient(web.app, headers={'Host': '[::1]:8091'}) if '[::1]' in base
              else TestClient(web.app, base_url=base))
    response = client.post('/api/auth/login', headers={'Origin': origin},
                           json={'username': 'admin', 'password': 'test-only-password'})
    assert response.status_code == 200
    assert response.json()['requires_password_change'] is False
    assert client.get('/api/config').status_code == 200


def test_forwarded_headers_do_not_change_origin_policy():
    client = TestClient(web.app)
    response = client.post('/api/auth/login', headers={'Origin': 'https://external.test',
                           'X-Forwarded-Host': 'external.test', 'X-Forwarded-Proto': 'https'},
                           json={'username': 'admin', 'password': 'test-only-password'})
    assert response.status_code == 403


@pytest.mark.parametrize('site', ['cross-site', 'same-site'])
def test_fetch_metadata_disallows_originless_cross_site_request(site):
    response = TestClient(web.app).post('/api/auth/login',
        headers={'X-Requested-With': 'Booksmith', 'Sec-Fetch-Site': site},
        json={'username': 'admin', 'password': 'test-only-password'})
    assert response.status_code == 403


def test_explicit_api_client_header_allows_originless_login_and_logout():
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-only-password'}).status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/status').json() == {'authenticated': False}


def test_origin_port_zero_is_not_equivalent_to_default_port():
    assert origin_identity('http://test:0') != origin_identity('http://test:80')


@pytest.mark.parametrize('path,status', [('/', 200), ('/static/app.js', 200),
                                       ('/api/config', 401), ('/missing', 404)])
def test_browser_headers_on_page_static_and_error_responses(path, status):
    response = TestClient(web.app).get(path)
    assert response.status_code == status
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    csp = response.headers['Content-Security-Policy']
    assert "script-src 'self';" in csp
    assert "frame-ancestors 'none'" in csp
    if path == '/' or path.startswith('/api/'):
        assert response.headers['Cache-Control'] == 'no-store'


def test_interactive_docs_disabled_but_schema_available():
    client = TestClient(web.app)
    assert client.get('/docs').status_code == 404
    assert client.get('/redoc').status_code == 404
    assert client.get('/openapi.json').status_code == 200


@pytest.mark.parametrize('password', ['a', 'x' * 11, ' ' * 12, ' x ' * 3, 'x' * 1025])
def test_new_environment_credentials_require_password_policy(tmp_path, password):
    path = tmp_path / 'auth.json'
    with pytest.raises(RuntimeError, match='Unsafe WebUI credentials'):
        load_credentials(path, 'admin', password)
    assert not path.exists()


@pytest.mark.parametrize('password', ['x' * 12, 'ż' * 12, 'x' * 1024])
def test_environment_password_policy_boundaries(tmp_path, password):
    _, encoded = load_credentials(tmp_path / 'auth.json', 'admin', password)
    assert verify_password(password, encoded)


@pytest.mark.parametrize('hashed', [False, True])
def test_legacy_weak_password_migrates_to_change_only_session(tmp_path, monkeypatch, hashed):
    path = tmp_path / 'auth.json'
    credentials = {'username': 'legacy', 'password_hash' if hashed else 'password':
                   hash_password('short') if hashed else 'short'}
    path.write_text(json.dumps(credentials))
    username, encoded = load_credentials(path, 'ignored', 'ignored')
    monkeypatch.setattr(web, 'APP_USERNAME', username)
    monkeypatch.setattr(web, 'APP_PASSWORD_HASH', encoded)
    monkeypatch.setattr(web, 'AUTH_FILE', path)
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    response = client.post('/api/auth/login', json={'username': 'legacy', 'password': 'short'})
    assert response.status_code == 200 and response.json()['requires_password_change'] is True
    assert client.get('/api/auth/status').json()['requires_password_change'] is True
    for target in ('/api/config', '/api/tasks', '/api/audio/not-found.mp3', '/api/progress?task_id=x'):
        assert client.get(target).status_code == 403
    token = client.cookies.get('session_id')
    receive, send = AsyncMock(), AsyncMock()
    scope = http_scope('/api/generate', [(b'cookie', f'session_id={token}'.encode()),
                                        (b'x-requested-with', b'Booksmith')])
    asyncio.run(web.app(scope, receive, send))
    assert send.await_args_list[0].args[0]['status'] == 403
    receive.assert_not_called()
    assert client.post('/api/auth/change-password', json={
        'current_password': 'short', 'new_password': 'stillshort'}).status_code == 400
    assert token in web.password_change_sessions
    assert client.post('/api/auth/change-password', json={
        'current_password': 'short', 'new_password': 'new long password'}).status_code == 200
    assert token not in web.active_sessions and not web.password_change_sessions
    assert client.get('/api/auth/status').json() == {'authenticated': False}
    saved = json.loads(path.read_text())
    assert 'password' not in saved and verify_password('new long password', saved['password_hash'])
    response = client.post('/api/auth/login', json={'username': 'legacy', 'password': 'new long password'})
    assert response.status_code == 200 and response.json()['requires_password_change'] is False
    assert client.get('/api/config').status_code == 200


def test_failed_password_write_keeps_change_only_session(monkeypatch):
    monkeypatch.setattr(web, 'APP_PASSWORD_HASH', hash_password('short'))
    monkeypatch.setattr(web, 'save_credentials', Mock(side_effect=OSError('simulated failure')))
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    client.post('/api/auth/login', json={'username': 'admin', 'password': 'short'})
    assert client.post('/api/auth/change-password', json={
        'current_password': 'short', 'new_password': 'new long password'}).status_code == 500
    assert client.get('/api/auth/status').json()['requires_password_change'] is True
    assert client.get('/api/config').status_code == 403
    assert client.post('/api/auth/logout').status_code == 200
    assert not web.password_change_sessions


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be'])
@pytest.mark.parametrize('declaration', ['<!DOCTYPE root SYSTEM "https://example.invalid/dtd">',
    '<!DOCTYPE root [<!ENTITY a "expansion"><!ENTITY b "&a;&a;&a;">]>',
    '<!DOCTYPE root [<!ENTITY % external SYSTEM "file:///never-open">%external;]>'])
def test_metadata_dtd_rejected_before_entities_for_all_supported_encodings(encoding, declaration):
    with pytest.raises(ValueError, match='DTD/entities'):
        strip_namespaces((declaration + '<root/>').encode(encoding))


def test_metadata_comment_is_not_mistaken_for_dtd():
    assert 'safe' in strip_namespaces(b'<root><!-- literal DOCTYPE text --><a>safe</a></root>')


@pytest.mark.parametrize('setting,content', [
    ('MAX_EPUB_XML_DEPTH', b'<a><b><c/></b></a>'),
    ('MAX_EPUB_XML_ELEMENTS', b'<a><b/><c/></a>'),
])
def test_metadata_tree_budget_boundaries(monkeypatch, setting, content):
    monkeypatch.setenv(setting, '3')
    assert strip_namespaces(content)
    monkeypatch.setenv(setting, '2')
    with pytest.raises(ResourceLimitExceeded, match=setting):
        strip_namespaces(content)


def test_epub_dtd_rejected_before_task_creation_and_valid_book_still_works(authenticated_web, monkeypatch, tmp_path):
    source = tmp_path / 'book.epub'
    create_mock_epub(source, [('chapter.xhtml', '<!DOCTYPE html><html><body>Good text.</body></html>')])
    valid = source.read_bytes()
    with zipfile.ZipFile(source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries['META-INF/container.xml'] = b'<!DOCTYPE container [<!ENTITY a "x">]><container/>'
    with zipfile.ZipFile(source, 'w') as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    pipeline, saved = AsyncMock(), Mock(wraps=web.save_job)
    monkeypatch.setattr(web, 'run_generation_pipeline', pipeline)
    monkeypatch.setattr(web, 'save_job', saved)
    client = TestClient(authenticated_web, headers={'X-Requested-With': 'Booksmith'},
                        cookies={'session_id': 'session-id'})
    response = client.post('/api/generate', data={'api_key': 'synthetic-key'},
                           files={'text_file': ('book.epub', source.read_bytes())})
    assert response.status_code == 400
    pipeline.assert_not_called()
    saved.assert_not_called()
    response = client.post('/api/generate', data={'api_key': 'synthetic-key'},
                           files={'text_file': ('book.epub', valid)})
    assert response.status_code == 200
    pipeline.assert_awaited_once()


def test_expired_change_only_session_does_not_leave_permission_state():
    web.active_sessions['expired'] = time.monotonic() - 1
    web.password_change_sessions.add('expired')
    assert not web.session_is_valid('expired')
    assert 'expired' not in web.password_change_sessions
