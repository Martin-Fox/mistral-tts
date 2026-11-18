"""Regressions for anonymous admission, pre-parse limits and upload deadlines."""
import asyncio
import json
import time
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from src import web
from src.web_limits import GenerationRequestLimits, JobController


def scope_for(path='/api/generate', headers=()):
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': 'POST', 'scheme': 'http', 'path': path,
            'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
            'headers': [(b'host', b'test'), (b'x-requested-with', b'Booksmith'), *headers],
            'server': ('test', 80), 'client': ('127.0.0.1', 12345)}


@pytest.mark.parametrize('path', ['/api/generate', '/api/resume/task-id'])
@pytest.mark.parametrize('token', [None, 'unknown', 'expired'])
def test_anonymous_requests_never_read_body_or_touch_admission(monkeypatch, path, token):
    web.active_sessions['expired'] = time.monotonic() - 1
    controller, budget, create_task = Mock(), Mock(), Mock()
    monkeypatch.setattr(web, 'job_controller', controller)
    monkeypatch.setattr(web, 'check_storage_budget', budget)
    monkeypatch.setattr(web.db, 'create_task', create_task)
    headers = [] if token is None else [(b'cookie', f'session_id={token}'.encode())]
    receive, send = AsyncMock(), AsyncMock()

    async def run():
        # More requests than the default four slots must all get 401, not 429.
        for _ in range(5):
            await web.app(scope_for(path, headers), receive, send)

    asyncio.run(run())
    statuses = [call.args[0]['status'] for call in send.await_args_list
                if call.args[0]['type'] == 'http.response.start']
    assert statuses == [401] * 5
    receive.assert_not_called()
    controller.admission.acquire.assert_not_called()
    budget.assert_not_called()
    create_task.assert_not_called()


@pytest.mark.parametrize('path', ['/api/auth/login', '/api/auth/change-password', '/api/config'])
@pytest.mark.parametrize('declared', [None, b'1', b'999'])
def test_control_body_limit_precedes_parsing_and_handlers(monkeypatch, path, declared):
    monkeypatch.setenv('MAX_JSON_REQUEST_BYTES', '10')
    app, controller = AsyncMock(), Mock()
    middleware = GenerationRequestLimits(app, lambda: controller, authenticated=lambda scope: False)
    headers = [] if declared is None else [(b'content-length', declared)]
    receive = AsyncMock(side_effect=[
        {'type': 'http.request', 'body': b'123456', 'more_body': True},
        {'type': 'http.request', 'body': b'123456', 'more_body': False},
    ])
    send = AsyncMock()
    asyncio.run(middleware(scope_for(path, headers), receive, send))
    assert send.await_args_list[0].args[0]['status'] == 413
    app.assert_not_called()
    controller.admission.acquire.assert_not_called()
    if declared == b'999':
        receive.assert_not_called()


def test_large_login_json_is_rejected_before_hashing_or_login_limiter(monkeypatch):
    verify, limiter = Mock(), Mock()
    monkeypatch.setattr(web, 'verify_password', verify)
    monkeypatch.setattr(web, 'login_limiter', limiter)
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    response = client.post('/api/auth/login', json={'username': 'a' * 65536, 'password': 'wrong'})
    assert response.status_code == 413
    verify.assert_not_called()
    limiter.consume.assert_not_called()


def test_mounted_app_cannot_bypass_early_authentication():
    scope = scope_for('/booksmith/api/generate')
    scope['root_path'] = '/booksmith'
    receive, send = AsyncMock(), AsyncMock()
    asyncio.run(web.app(scope, receive, send))
    assert send.await_args_list[0].args[0]['status'] == 401
    receive.assert_not_called()


@pytest.mark.parametrize('field,value', [('username', 'a' * 257), ('password', 'ż' * 1025)])
def test_login_field_lengths_are_bounded_before_hashing(monkeypatch, field, value):
    verify = Mock()
    monkeypatch.setattr(web, 'verify_password', verify)
    payload = {'username': 'admin', 'password': 'wrong', field: value}
    assert TestClient(web.app, headers={'X-Requested-With': 'Booksmith'}).post('/api/auth/login', json=payload).status_code == 422
    verify.assert_not_called()


@pytest.mark.parametrize('field', ['current_password', 'new_password'])
def test_password_change_field_lengths_are_bounded(monkeypatch, field):
    verify = Mock()
    monkeypatch.setattr(web, 'verify_password', verify)
    web.active_sessions['valid'] = time.monotonic() + 3600
    payload = {'current_password': 'wrong', 'new_password': 'new-password', field: 'x' * 1025}
    response = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'}, cookies={'session_id': 'valid'}).post(
        '/api/auth/change-password', json=payload)
    assert response.status_code == 422
    verify.assert_not_called()


@pytest.mark.parametrize('kind', ['idle', 'total'])
def test_upload_deadlines_close_spool_and_release_admission(monkeypatch, kind):
    from src import web_limits
    monkeypatch.setenv('REQUEST_BODY_TIMEOUT_SECONDS', '1' if kind == 'total' else '3')
    monkeypatch.setenv('REQUEST_BODY_IDLE_TIMEOUT_SECONDS', '1' if kind == 'idle' else '3')
    spools = []
    spool_factory = web_limits.tempfile.SpooledTemporaryFile
    def track_spool(*args, **kwargs):
        spool = spool_factory(*args, **kwargs)
        spools.append(spool)
        return spool
    monkeypatch.setattr(web_limits.tempfile, 'SpooledTemporaryFile', track_spool)
    controller, downstream = JobController(1, 0), AsyncMock()
    middleware = GenerationRequestLimits(downstream, lambda: controller,
                                         authenticated=lambda scope: True)
    received = 0
    async def receive():
        nonlocal received
        received += 1
        if kind == 'idle':
            await asyncio.Event().wait()
        else:
            await asyncio.sleep(0.1)
        return {'type': 'http.request', 'body': b'x', 'more_body': True}
    send = AsyncMock()
    asyncio.run(middleware(scope_for(), receive, send))
    assert send.await_args_list[0].args[0]['status'] == 408
    downstream.assert_not_called()
    assert spools and all(spool.closed for spool in spools)
    assert received > 1 if kind == 'total' else received == 1
    assert controller.admission.acquire(False)
    controller.admission.release()
    # A normal request can reuse the slot immediately after a timed-out upload.
    receive_ok = AsyncMock(return_value={'type': 'http.request', 'body': b'', 'more_body': False})
    asyncio.run(middleware(scope_for(), receive_ok, AsyncMock()))
    downstream.assert_awaited_once()


def test_upload_deadline_does_not_cancel_background_generation(monkeypatch):
    monkeypatch.setenv('REQUEST_BODY_TIMEOUT_SECONDS', '1')
    controller = JobController(1, 0)
    finished = []
    async def app(scope, receive, send):
        assert (await receive())['body'] == b'complete'
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})
        await asyncio.sleep(1.1)  # BackgroundTasks remain inside the app call.
        finished.append(True)
    middleware = GenerationRequestLimits(app, lambda: controller, authenticated=lambda scope: True)
    receive = AsyncMock(return_value={'type': 'http.request', 'body': b'complete', 'more_body': False})
    asyncio.run(middleware(scope_for(), receive, AsyncMock()))
    assert finished == [True]
    assert controller.admission.acquire(False)
    controller.admission.release()


def test_revoked_session_is_rechecked_after_upload(monkeypatch):
    web.active_sessions['valid'] = time.monotonic() + 3600
    create_task = Mock()
    monkeypatch.setattr(web.db, 'create_task', create_task)
    body = b'api_key=fake-key&text_content=hello'
    async def receive():
        web.active_sessions.clear()  # Logout/password change while upload is in progress.
        return {'type': 'http.request', 'body': body, 'more_body': False}
    send = AsyncMock()
    scope = scope_for(headers=[(b'cookie', b'session_id=valid'),
                               (b'content-type', b'application/x-www-form-urlencoded')])
    asyncio.run(web.app(scope, receive, send))
    assert send.await_args_list[0].args[0]['status'] == 401
    create_task.assert_not_called()


def test_valid_unicode_login_and_exact_body_boundary(monkeypatch):
    payload = json.dumps({'username': 'żółw', 'password': 'test-only-password'}).encode()
    monkeypatch.setattr(web, 'APP_USERNAME', 'żółw')
    monkeypatch.setenv('MAX_JSON_REQUEST_BYTES', str(len(payload)))
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    response = client.post('/api/auth/login', content=payload, headers={'Content-Type': 'application/json'})
    assert response.status_code == 200
    assert client.get('/api/auth/status').json()['authenticated'] is True
    response = client.post('/api/auth/login', content=payload + b' ', headers={'Content-Type': 'application/json'})
    assert response.status_code == 413


@pytest.mark.parametrize('setting', ['MAX_JSON_REQUEST_BYTES', 'REQUEST_BODY_TIMEOUT_SECONDS',
                                   'REQUEST_BODY_IDLE_TIMEOUT_SECONDS'])
@pytest.mark.parametrize('value', ['0', '-1', 'bad'])
def test_new_limits_are_validated_at_startup(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=setting):
        asyncio.run(web.startup_event())
