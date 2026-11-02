import asyncio
import io
import zipfile
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from src import web
from src.core.epub_parser import extract_text_from_epub, read_input_text
from src.core.resource_limits import ResourceLimits, ResourceLimitExceeded
from src.web_limits import GenerationRequestLimits, JobController
from test_epub import create_mock_epub


@pytest.fixture
def limited_web(monkeypatch):
    monkeypatch.setattr(web, 'db', Mock())
    monkeypatch.setattr(web, 'job_controller', JobController(2, 2))
    pipeline = AsyncMock()
    monkeypatch.setattr(web, 'run_generation_pipeline', pipeline)
    monkeypatch.setitem(web.app.dependency_overrides, web.verify_session, lambda: 'test-session')
    return TestClient(web.app), pipeline


@pytest.mark.parametrize('setting', ['MAX_REQUEST_BYTES', 'MAX_TEXT_CHARS', 'MAX_RUNNING_JOBS'])
@pytest.mark.parametrize('value', ['0', '-1', 'bad'])
def test_invalid_configuration_is_rejected(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        ResourceLimits.from_env()


def test_text_boundary_does_not_truncate(tmp_path, monkeypatch):
    monkeypatch.setenv('MAX_TEXT_CHARS', '5')
    path = tmp_path / 'book.txt'
    path.write_text('abcde')
    assert read_input_text(path) == 'abcde'
    path.write_text('abcdef')
    with pytest.raises(ResourceLimitExceeded):
        read_input_text(path)


def test_inline_limit_returns_413_without_creating_task(limited_web, monkeypatch):
    client, pipeline = limited_web
    monkeypatch.setenv('MAX_TEXT_CHARS', '5')
    response = client.post('/api/generate', data={'api_key': 'fake-key', 'text_content': 'abcdef'})
    assert response.status_code == 413
    pipeline.assert_not_called()
    web.db.create_task.assert_not_called()
    response = client.post('/api/generate', data={'api_key': 'fake-key', 'text_content': 'abcde'})
    assert response.status_code == 200
    pipeline.assert_awaited_once()


@pytest.mark.parametrize(('field', 'setting'), [
    ('text_file', 'MAX_TEXT_UPLOAD_BYTES'), ('voice_file', 'MAX_VOICE_UPLOAD_BYTES'),
])
def test_file_limits_reject_before_pipeline(limited_web, monkeypatch, field, setting):
    client, pipeline = limited_web
    monkeypatch.setenv(setting, '5')
    response = client.post('/api/generate', data={'api_key': 'fake-key', 'text_content': 'text'},
                           files={field: ('sample.txt', b'123456')})
    assert response.status_code == 413
    pipeline.assert_not_called()
    web.db.create_task.assert_not_called()


def test_upload_reads_are_bounded(monkeypatch):
    upload = UploadFile(io.BytesIO(b'x' * 100))
    read = AsyncMock(wraps=upload.read)
    monkeypatch.setattr(upload, 'read', read)
    async def run():
        with pytest.raises(web.HTTPException) as error:
            await web.read_upload_bounded(upload, 5)
        assert error.value.status_code == 413
    asyncio.run(run())
    assert read.call_args.args[0] == 6


@pytest.mark.parametrize(('setting', 'value'), [
    ('MAX_EPUB_BYTES', '1000'), ('MAX_EPUB_ENTRY_BYTES', '1000'),
    ('MAX_EPUB_ENTRIES', '2'), ('MAX_TEXT_CHARS', '5'),
])
def test_epub_budgets_use_small_synthetic_archives(tmp_path, monkeypatch, setting, value):
    path = tmp_path / 'book.epub'
    create_mock_epub(path, [('one.xhtml', '<html><body>' + 'x' * 2000 + '</body></html>')])
    monkeypatch.setenv(setting, value)
    with pytest.raises(ResourceLimitExceeded):
        extract_text_from_epub(path)


def test_compressed_epub_is_rejected_before_decompression(tmp_path, monkeypatch):
    path = tmp_path / 'small.epub'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('large.xhtml', 'x' * 10000)
    monkeypatch.setenv('MAX_EPUB_ENTRY_BYTES', '1000')
    with pytest.raises(ResourceLimitExceeded):
        extract_text_from_epub(path)


def test_epub_preflight_returns_413_before_pipeline(limited_web, monkeypatch, tmp_path):
    client, pipeline = limited_web
    path = tmp_path / 'book.epub'
    create_mock_epub(path, [('one.xhtml', '<html><body>too much text</body></html>')])
    monkeypatch.setenv('MAX_TEXT_CHARS', '5')
    response = client.post('/api/generate', data={'api_key': 'fake-key'},
                           files={'text_file': ('book.epub', path.read_bytes())})
    assert response.status_code == 413
    pipeline.assert_not_called()
    web.db.create_task.assert_not_called()


@pytest.mark.parametrize('declared', [None, b'1', b'999'])
def test_body_budget_includes_chunked_and_forged_lengths(monkeypatch, declared):
    monkeypatch.setenv('MAX_REQUEST_BYTES', '10')
    controller = JobController(1, 0)
    app = AsyncMock()
    middleware = GenerationRequestLimits(app, controller=lambda: controller)
    headers = [] if declared is None else [(b'content-length', declared)]
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/generate', 'headers': headers}
    receive = AsyncMock(side_effect=[
        {'type': 'http.request', 'body': b'123456', 'more_body': True},
        {'type': 'http.request', 'body': b'123456', 'more_body': False},
    ])
    sent = []
    async def send(message):
        sent.append(message)
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]['status'] == 413
    app.assert_not_called()
    if declared == b'999':
        receive.assert_not_called()
    assert controller.admission.acquire(blocking=False)
    controller.admission.release()


def test_busy_capacity_returns_429_before_reading_body():
    controller = JobController(1, 1)
    assert controller.admission.acquire(False)
    assert controller.admission.acquire(False)
    middleware = GenerationRequestLimits(AsyncMock(), controller=lambda: controller)
    receive = AsyncMock()
    sent = []
    async def send(message):
        sent.append(message)
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/generate', 'headers': []}
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]['status'] == 429
    assert (b'retry-after', b'5') in sent[0]['headers']
    receive.assert_not_called()
    controller.admission.release()
    controller.admission.release()


def test_running_limit_and_cancelled_waiter_do_not_leak_slots():
    controller = JobController(1, 1)
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        active = 0
        maximum = 0
        async def work():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            started.set()
            await finish.wait()
            active -= 1
        owner = asyncio.create_task(controller.run(work))
        await started.wait()
        waiter = asyncio.create_task(controller.run(work))
        await asyncio.sleep(0.01)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        finish.set()
        await owner
        await controller.run(work)
        assert maximum == 1
    asyncio.run(run())


def test_large_inline_multipart_field_uses_configured_budget(limited_web, monkeypatch):
    client, pipeline = limited_web
    monkeypatch.setenv('MAX_TEXT_CHARS', '1100000')
    response = client.post('/api/generate', data={'api_key': 'fake-key'},
                           files={'text_content': (None, 'x' * 1050000)})
    assert response.status_code == 200
    pipeline.assert_awaited_once()


@pytest.mark.parametrize('outcome', ['error', 'cancel', 'disconnect'])
def test_transport_admission_is_released_on_failure(outcome):
    controller = JobController(1, 0)
    async def app(scope, receive, send):
        if outcome == 'error':
            raise RuntimeError('simulated error')
        raise asyncio.CancelledError
    middleware = GenerationRequestLimits(app, controller=lambda: controller)
    receive = AsyncMock(return_value={
        'type': 'http.disconnect' if outcome == 'disconnect' else 'http.request',
        'body': b'', 'more_body': False,
    })
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/generate', 'headers': []}
    async def run():
        if outcome == 'disconnect':
            await middleware(scope, receive, AsyncMock())
        else:
            with pytest.raises((RuntimeError, asyncio.CancelledError)):
                await middleware(scope, receive, AsyncMock())
    asyncio.run(run())
    assert controller.admission.acquire(False)
    controller.admission.release()


def test_http_queue_is_bounded_and_capacity_is_reused(limited_web, monkeypatch):
    import httpx
    _, pipeline = limited_web
    monkeypatch.setattr(web, 'job_controller', JobController(1, 1))
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        async def work(**kwargs):
            started.set()
            await finish.wait()
        pipeline.side_effect = work
        transport = httpx.ASGITransport(app=web.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            payload = {'api_key': 'fake-key', 'text_content': 'text'}
            first = asyncio.create_task(client.post('/api/generate', data=payload))
            second = asyncio.create_task(client.post('/api/generate', data=payload))
            try:
                await asyncio.wait_for(started.wait(), 2)
                for _ in range(200):
                    if web.db.create_task.call_count == 2:
                        break
                    await asyncio.sleep(0.005)
                assert web.db.create_task.call_count == 2
                assert pipeline.await_count == 1
                rejected = await client.post('/api/generate', data=payload)
                assert rejected.status_code == 429
            finally:
                finish.set()
                results = await asyncio.gather(first, second)
            assert [result.status_code for result in results] == [200, 200]
            assert pipeline.await_count == 2
            assert (await client.post('/api/generate', data=payload)).status_code == 200
            assert pipeline.await_count == 3
    asyncio.run(run())


def test_urlencoded_field_count_is_bounded(limited_web):
    client, pipeline = limited_web
    payload = '&'.join(f'field{i}=x' for i in range(33))
    response = client.post('/api/generate', content=payload,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    assert response.status_code == 413
    pipeline.assert_not_called()


def test_repeated_epub_spine_reads_consume_budget(tmp_path, monkeypatch):
    path = tmp_path / 'book.epub'
    create_mock_epub(path, [('one.xhtml', '<html><body>chapter text</body></html>')])
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries['OEBPS/content.opf'] = entries['OEBPS/content.opf'].replace(
        b'<itemref idref="chap_0"/>', b'<itemref idref="chap_0"/><itemref idref="chap_0"/>')
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    monkeypatch.setenv('MAX_EPUB_BYTES', str(sum(map(len, entries.values()))))
    with pytest.raises(ResourceLimitExceeded, match='decompression budget'):
        extract_text_from_epub(path)


def test_malformed_epub_rejected_without_pipeline(limited_web):
    client, pipeline = limited_web
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('META-INF/container.xml', '<invalid')
    response = client.post('/api/generate', data={'api_key': 'fake-key'},
                           files={'text_file': ('book.epub', data.getvalue())})
    assert response.status_code == 400
    pipeline.assert_not_called()
    web.db.create_task.assert_not_called()


def test_failed_background_work_releases_worker_and_admission(limited_web, monkeypatch):
    client, pipeline = limited_web
    monkeypatch.setattr(web, 'job_controller', JobController(1, 0))
    pipeline.side_effect = RuntimeError('background failure')
    payload = {'api_key': 'fake-key', 'text_content': 'text'}
    with pytest.raises(RuntimeError, match='background failure'):
        client.post('/api/generate', data=payload)
    pipeline.side_effect = None
    assert client.post('/api/generate', data=payload).status_code == 200
