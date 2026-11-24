import asyncio
import sqlite3
import time
import os
import uuid
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
import pytest

from src import web
from src.core import task_store
from src.core.task_db import TaskDatabase
from src.core.task_store import save_job, load_job, task_directory
from src.api.mistral_client import MistralTTSClient


@pytest.mark.anyio
@pytest.mark.parametrize('enabled', [False, True])
async def test_periodic_retention_preserves_failed_and_defaults_to_dry_run(tmp_path, monkeypatch, enabled):
    import asyncio
    root = tmp_path / 'storage'
    database = TaskDatabase(root / 'state.db')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web, 'db', database)
    monkeypatch.setattr(web.global_log_handler, 'database', database)
    monkeypatch.setattr(task_store, 'TASK_ROOT', root / 'tasks')
    if enabled:
        monkeypatch.setenv('STORAGE_CLEANUP_ENABLED', 'true')
    else:
        monkeypatch.delenv('STORAGE_CLEANUP_ENABLED', raising=False)
    ids = {}
    for status in ('Completed', 'Failed'):
        task_id = str(uuid.uuid4())
        ids[status] = task_id
        database.create_task(task_id)
        database.update_task(task_id, status=status, completed=status == 'Completed')
        save_job(task_id, {'text_content': 'retained original'})
        directory = task_directory(task_id)
        for path in [*directory.iterdir(), directory]:
            os.utime(path, (1, 1))
        with database._get_connection() as connection:
            connection.execute('UPDATE tasks SET finished_at=0 WHERE id=?', (task_id,))
    monkeypatch.setattr(web.asyncio, 'sleep', AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await web.task_purger_loop()
    assert database.get_task(ids['Failed']) is not None
    assert task_directory(ids['Failed']).joinpath('spec.json').exists()
    assert (database.get_task(ids['Completed']) is None) == enabled
    assert task_directory(ids['Completed']).exists() != enabled


def test_migration_restart_and_retention(tmp_path):
    path = tmp_path / 'state.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY,percentage INTEGER DEFAULT 0,status TEXT DEFAULT "Pending",'
                     'completed INTEGER DEFAULT 0,audio_file TEXT,error TEXT,created_at REAL NOT NULL)')
        conn.execute('INSERT INTO tasks (id,status,completed,created_at) VALUES ("old","Completed",1,0)')
    db = TaskDatabase(path)
    assert db.get_task('old')['finished_at'] > time.time() - 5
    db.create_task('active')
    db.update_task('active', percentage=50, status='Generating Audio')
    db.add_log('active', 'persisted log')
    with db._get_connection() as conn:
        conn.execute('UPDATE tasks SET created_at=0 WHERE id="active"')
    assert db.delete_old_tasks(time.time() - 86400) == 0
    restarted = TaskDatabase(path)
    assert restarted.interrupt_unfinished_tasks() == 1
    interrupted = restarted.get_task('active')
    assert interrupted['status'] == 'Interrupted'
    assert interrupted['percentage'] == 50
    assert restarted.get_logs('active')[0]['message'] == 'persisted log'
    assert restarted.interrupt_unfinished_tasks() == 0
    assert restarted.delete_old_tasks(time.time() - 86400) == 0
    with restarted._get_connection() as conn:
        conn.execute('UPDATE tasks SET finished_at=0 WHERE id="old"')
    assert restarted.delete_old_tasks(time.time() - 86400) == 1
    assert restarted.get_task('active') is not None
    assert restarted.claim_resume('active')
    assert not restarted.claim_resume('active')
    assert restarted.get_task('active')['error'] is None
    assert restarted.get_task('active')['finished_at'] is None


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(task_store, 'TASK_ROOT', tmp_path / 'tasks')
    db = TaskDatabase(tmp_path / 'state.db')
    monkeypatch.setattr(web, 'db', db)
    monkeypatch.setattr(web.global_log_handler, 'database', db)
    monkeypatch.setattr(web, 'job_controller', web.JobController(2, 2))
    monkeypatch.setitem(web.app.dependency_overrides, web.verify_session, lambda: 'session')
    web.active_sessions['session'] = time.monotonic() + 3600
    return db, TestClient(web.app, headers={'X-Requested-With': 'Booksmith'}, cookies={'session_id': 'session'})


def test_resume_quota_recheck_does_not_claim_or_run_task(recovery, monkeypatch):
    from src.core.storage_retention import StorageBudgetExceeded
    database, client = recovery
    task_id = str(uuid.uuid4())
    database.create_task(task_id)
    database.update_task(task_id, status='Failed')
    save_job(task_id, {'text_content': 'hello'})
    budget = Mock(side_effect=[None, StorageBudgetExceeded('Not enough room for working copy')])
    monkeypatch.setattr(web, 'check_storage_budget', budget)
    claim = Mock(wraps=database.claim_resume)
    monkeypatch.setattr(database, 'claim_resume', claim)
    pipeline = AsyncMock()
    monkeypatch.setattr(web, 'run_generation_pipeline', pipeline)
    response = client.post(f'/api/resume/{task_id}', data={'api_key': 'fake-key'})
    assert response.status_code == 507
    assert budget.call_args.kwargs['additional_bytes'] == 5
    assert database.get_task(task_id)['status'] == 'Failed'
    claim.assert_not_called()
    pipeline.assert_not_called()


def test_resume_preserves_inputs_cache_and_excludes_keys(recovery, monkeypatch):
    db, client = recovery
    generated = []
    async def generate(text, output):
        generated.append(text)
        if len(generated) == 2:
            raise RuntimeError('simulated failure')
        output.write_bytes(text.encode() * 200)
    tts = Mock(model='voxtral-mini-tts-2603')
    tts.generate_audio = AsyncMock(side_effect=generate)
    monkeypatch.setattr(web, 'get_tts_client', Mock(return_value=tts))
    splitter = Mock(max_chars=1000)
    splitter.split.return_value = ['first', 'second']
    monkeypatch.setattr(web, 'TextSplitter', Mock(return_value=splitter))
    monkeypatch.setattr(web, 'AudioCompiler', Mock(return_value=Mock(compile=Mock(return_value={}))))
    task_id = client.post('/api/generate', data={
        'api_key': 'secret-do-not-persist', 'text_content': 'original text'}).json()['task_id']
    assert db.get_task(task_id)['status'] == 'Failed'
    spec = (task_directory(task_id) / 'spec.json').read_text()
    assert 'secret-do-not-persist' not in spec
    assert load_job(task_id)['text_file_data'][1] == b'original text'
    assert client.get('/api/tasks').json()['tasks'][0]['id'] == task_id
    # Simulate a new database handle after restart, retaining files and cache.
    monkeypatch.setattr(web, 'db', TaskDatabase(db.db_path))
    response = client.post(f'/api/resume/{task_id}', data={'api_key': 'new-secret'})
    assert response.status_code == 200
    assert generated == ['first', 'second', 'second']
    assert db.get_task(task_id)['status'] == 'Completed'
    assert client.post(f'/api/resume/{task_id}', data={'api_key': 'new-secret'}).status_code == 409
    assert client.get('/api/tasks').json()['tasks'] == []


def test_resume_rejects_missing_keys_or_changed_input(recovery, monkeypatch):
    db, client = recovery
    task_id = str(uuid.uuid4())
    save_job(task_id, dict(text_content='original', engine='mistral', output_filename='out.mp3'))
    db.create_task(task_id)
    db.interrupt_unfinished_tasks()
    monkeypatch.delenv('MISTRAL_API_KEY', raising=False)
    assert client.post(f'/api/resume/{task_id}').status_code == 400
    data = task_directory(task_id) / 'text.txt'
    data.write_text('changed')
    assert client.post(f'/api/resume/{task_id}', data={'api_key': 'fake'}).status_code == 409
    assert db.get_task(task_id)['status'] == 'Interrupted'


def test_translation_response_checkpoints_survive_new_client(tmp_path):
    calls = []
    def client():
        instance = MistralTTSClient('fake-key')
        instance.translation_cache_dir = tmp_path
        response = Mock()
        response.choices = [Mock(message=Mock(content='translated'), finish_reason='stop')]
        async def complete(**kwargs):
            calls.append(kwargs)
            return response
        instance.client = Mock(chat=Mock(complete_async=complete))
        return instance
    async def run():
        assert await client().translate_text('source', 'English', 'Polish') == 'translated'
        assert await client().translate_text('source', 'English', 'Polish') == 'translated'
    asyncio.run(run())
    assert len(calls) == 1
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_corrupt_translation_checkpoint_is_retried_not_fatal(tmp_path):
    calls = []
    def client():
        instance = MistralTTSClient('fake-key')
        instance.translation_cache_dir = tmp_path
        response = Mock()
        response.choices = [Mock(message=Mock(content='translated'), finish_reason='stop')]
        async def complete(**kwargs):
            calls.append(kwargs)
            return response
        instance.client = Mock(chat=Mock(complete_async=complete))
        return instance
    async def run():
        assert await client().translate_text('source', 'English', 'Polish') == 'translated'
    asyncio.run(run())
    assert len(calls) == 1

    # Corrupt JSON on disk: treated as a cache miss, the block is re-translated.
    for path in tmp_path.glob('*.json'):
        path.write_text('{not valid json', encoding='utf-8')
    asyncio.run(run())
    assert len(calls) == 2

    # Valid JSON but empty content: also a miss, never a job failure.
    for path in tmp_path.glob('*.json'):
        path.write_text('{"content": "   ", "finish_reason": "stop"}', encoding='utf-8')
    asyncio.run(run())
    assert len(calls) == 3


def test_restart_during_compilation_reuses_completed_audio(recovery, monkeypatch):
    db, client = recovery
    task_id = str(uuid.uuid4())
    save_job(task_id, dict(text_content='original', engine='mistral', output_filename='out.mp3'))
    db.create_task(task_id)
    async def generate(text, path):
        path.write_bytes(b'complete-audio' * 100)
    tts = Mock(model='voxtral-mini-tts-2603')
    tts.generate_audio = AsyncMock(side_effect=generate)
    monkeypatch.setattr(web, 'get_tts_client', Mock(return_value=tts))
    compiler = Mock()
    compiler.compile.side_effect = asyncio.CancelledError()
    monkeypatch.setattr(web, 'AudioCompiler', Mock(return_value=compiler))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(web.run_generation_pipeline(task_id=task_id, api_key='fake', **load_job(task_id)))
    restarted = TaskDatabase(db.db_path)
    assert restarted.interrupt_unfinished_tasks() == 1
    monkeypatch.setattr(web, 'db', restarted)
    def finish(chunks, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(chunks[0].read_bytes())
        return {}
    compiler.compile.side_effect = finish
    assert client.post(f'/api/resume/{task_id}', data={'api_key': 'fake'}).status_code == 200
    assert restarted.get_task(task_id)['completed']
    tts.generate_audio.assert_awaited_once()


def killed_generation_worker(root, task_id, ready):
    import os
    from pathlib import Path
    os.chdir(root)
    task_store.TASK_ROOT = Path(root) / 'tasks'
    web.db = TaskDatabase(Path(root) / 'state.db')
    web.global_log_handler.database = web.db
    splitter = Mock(max_chars=1000)
    splitter.split.return_value = ['first', 'second']
    web.TextSplitter = Mock(return_value=splitter)
    async def generate(text, path):
        path.write_bytes(b'complete-audio' * 100)
        if text == 'second':
            ready.set()
            await asyncio.sleep(3600)
    tts = Mock(model='voxtral-mini-tts-2603')
    tts.generate_audio = AsyncMock(side_effect=generate)
    web.get_tts_client = Mock(return_value=tts)
    asyncio.run(web.run_generation_pipeline(task_id=task_id, api_key='fake', **load_job(task_id)))


def test_killed_process_resumes_only_unfinished_segments(recovery, monkeypatch, tmp_path):
    import multiprocessing
    db, client = recovery
    task_id = str(uuid.uuid4())
    save_job(task_id, dict(text_content='original', engine='mistral', output_filename='out.mp3'))
    db.create_task(task_id)
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    worker = ctx.Process(target=killed_generation_worker, args=(str(tmp_path), task_id, ready))
    worker.start()
    try:
        assert ready.wait(10)
        worker.terminate()
        worker.join(5)
        assert not worker.is_alive()
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
    assert db.interrupt_unfinished_tasks() == 1
    async def generate(text, path):
        path.write_bytes(b'complete-audio' * 100)
    tts = Mock(model='voxtral-mini-tts-2603')
    tts.generate_audio = AsyncMock(side_effect=generate)
    monkeypatch.setattr(web, 'get_tts_client', Mock(return_value=tts))
    splitter = Mock(max_chars=1000)
    splitter.split.return_value = ['first', 'second']
    monkeypatch.setattr(web, 'TextSplitter', Mock(return_value=splitter))
    monkeypatch.setattr(web, 'AudioCompiler', Mock(return_value=Mock(compile=Mock(return_value={}))))
    assert client.post(f'/api/resume/{task_id}', data={'api_key': 'fake'}).status_code == 200
    assert db.get_task(task_id)['completed']
    assert [call.args[0] for call in tts.generate_audio.await_args_list] == ['second']
