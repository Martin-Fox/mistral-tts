import asyncio
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import json
import subprocess
import sys
import time
from unittest.mock import AsyncMock, Mock
import uuid

import pytest

from src.core import task_store
from src.core.cache_io import generate_chunk_atomic, try_directory_lock
from src.core.storage_retention import (StoragePolicy, StorageBudgetExceeded,
                                        check_storage_budget, sweep_storage)
from src.core.task_db import TaskDatabase
from src.web_limits import GenerationRequestLimits, JobController


def age(path):
    stamp = time.time() - 2_000_000
    if path.is_dir():
        for child in path.rglob('*'):
            os.utime(child, (stamp, stamp), follow_symlinks=False)
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def write(path, data=b'data'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / 'storage'
    database = TaskDatabase(root / 'state.db')
    monkeypatch.setattr(task_store, 'TASK_ROOT', root / 'tasks')
    monkeypatch.chdir(tmp_path)
    return root, database


def job(store, status, *, old=True):
    root, database = store
    task_id = str(uuid.uuid4())
    task_store.save_job(task_id, {'text_content': 'complete original input'})
    database.create_task(task_id)
    database.update_task(task_id, status=status, completed=status == 'Completed')
    if old:
        with database._get_connection() as connection:
            connection.execute('UPDATE tasks SET finished_at=0 WHERE id=?', (task_id,))
    key = 'v2_' + hashlib.sha256(task_id.encode()).hexdigest()
    task_store.save_cache_reference(task_id, key)
    cache = root / 'cache' / key
    write(cache / '.cache.lock', b'')
    write(cache / 'chunk_0000.mp3', b'cached audio' * 20)
    write(cache / 'manifest.json', b'{}')
    age(cache)
    age(task_store.task_directory(task_id))
    return task_id, cache


@pytest.mark.parametrize('status', ['Pending', 'Generating Audio', 'Failed', 'Interrupted', 'Completed'])
def test_active_resumable_and_recent_completed_artifacts_survive(store, status):
    root, database = store
    task_id, cache = job(store, status, old=status != 'Completed')
    output = write(root / 'output' / f'{task_id}_book.mp3')
    age(output)
    report = sweep_storage(root, database.db_path, dry_run=False)
    assert database.get_task(task_id) is not None
    assert cache.joinpath('chunk_0000.mp3').exists()
    assert task_store.task_directory(task_id).joinpath('spec.json').exists()
    assert output.exists()
    assert not report['candidates']


def test_expired_completed_artifacts_and_logs_removed_but_lock_inode_retained(store):
    root, database = store
    task_id, cache = job(store, 'Completed')
    database.add_log(task_id, 'old log')
    output = write(root / 'output' / f'{task_id}_book.mp3')
    translation = write(root / 'translations' / f'{task_id}_translated.txt')
    scratch = write(root / 'cache' / f'task_{task_id}' / 'input.txt').parent
    for path in (output, translation, scratch):
        age(path)
    database.update_task(task_id, audio_file=output.name)
    lock_inode = (cache / '.cache.lock').stat().st_ino
    unknown = write(root / 'output' / 'user-book.mp3', b'preserve unknown output')
    credentials = write(root / 'auth.json', b'preserve auth metadata')
    report = sweep_storage(root, database.db_path, dry_run=False)
    assert task_id in report['expired_tasks']
    assert database.get_task(task_id) is None
    assert database.get_logs(task_id) == []
    assert not output.exists() and not translation.exists() and not scratch.exists()
    assert not task_store.task_directory(task_id).exists()
    assert list(cache.iterdir()) == [cache / '.cache.lock']
    assert (cache / '.cache.lock').stat().st_ino == lock_inode
    assert unknown.read_bytes() == b'preserve unknown output'
    assert credentials.read_bytes() == b'preserve auth metadata'
    assert not sweep_storage(root, database.db_path, dry_run=False)['candidates']


def snapshot(root):
    return {str(path.relative_to(root)): (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
            for path in [root, *root.rglob('*')]}


def test_dry_run_is_read_only_and_apply_replans(store):
    root, database = store
    task_id, cache = job(store, 'Completed')
    before = snapshot(root)
    report = sweep_storage(root, database.db_path)
    assert report['dry_run'] is True
    assert report['candidates'] and task_id in report['expired_tasks']
    assert snapshot(root) == before
    # A newly-created failed job pins that same cache before apply.
    other, _ = job(store, 'Failed')
    task_store.save_cache_reference(other, cache.name)
    sweep_storage(root, database.db_path, dry_run=False)
    assert (cache / 'chunk_0000.mp3').exists()


@pytest.mark.parametrize('marker', ['missing', 'corrupt', 'traversal'])
def test_unknown_cache_mapping_protects_all_caches(store, marker):
    root, database = store
    task_id, _ = job(store, 'Interrupted')
    path = task_store.task_directory(task_id) / 'cache.json'
    if marker == 'missing':
        path.unlink()
    else:
        path.write_text('not-json' if marker == 'corrupt' else '{"cache_key":"../../outside"}')
    orphan = write(root / 'cache' / ('v2_' + 'a' * 64) / 'chunk_0000.mp3').parent
    age(orphan)
    sweep_storage(root, database.db_path, dry_run=False)
    assert orphan.joinpath('chunk_0000.mp3').exists()


def test_only_old_orphans_are_removed(store):
    root, database = store
    orphan = write(root / 'tasks' / ('a' * 64) / '.pending-input.txt').parent
    fresh = write(root / 'tasks' / ('b' * 64) / 'input.txt').parent
    output = write(root / 'output' / f'{uuid.uuid4()}_book.mp3')
    compiler = write(root / 'output' / '.compile-abandoned' / 'result.mp3').parent
    write(compiler / '.cache.lock', b'')
    for path in (orphan, output, compiler):
        age(path)
    sweep_storage(root, database.db_path, dry_run=False)
    assert not orphan.exists() and not output.exists() and not compiler.exists()
    assert fresh.joinpath('input.txt').exists()


@pytest.mark.parametrize('kind', ['cache', 'compiler'])
def test_busy_resources_survive_even_with_very_old_timestamps(store, kind):
    root, database = store
    path = root / ('cache' if kind == 'cache' else 'output') / ('v2_' + 'a' * 64 if kind == 'cache' else '.compile-busy')
    payload = write(path / 'chunk.mp3')
    with try_directory_lock(path) as acquired:
        assert acquired
        age(path)
        report = sweep_storage(root, database.db_path, dry_run=False)
        assert payload.exists()
        assert str(path.relative_to(root)) in report['skipped']
    sweep_storage(root, database.db_path, dry_run=False)
    assert not payload.exists()


def test_busy_sweep_does_not_run_a_second_deleter(store):
    root, database = store
    with try_directory_lock(root, '.retention.lock'):
        report = sweep_storage(root, database.db_path, dry_run=False)
    assert report['skipped'] == ['Another retention sweep is running']


@pytest.mark.parametrize('location', ['root', 'area', 'tree'])
def test_symlinks_never_allow_deletion_outside_storage(store, tmp_path, location):
    root, database = store
    external = write(tmp_path / 'external' / 'keep.txt', b'external content').parent
    age(external)
    if location == 'root':
        linked_root = tmp_path / 'linked-storage'
        linked_root.symlink_to(external, target_is_directory=True)
        with pytest.raises(ValueError, match='symbolic link'):
            sweep_storage(linked_root, database.db_path, dry_run=False)
    elif location == 'area':
        (root / 'cache').symlink_to(external, target_is_directory=True)
        sweep_storage(root, database.db_path, dry_run=False)
    else:
        candidate = write(root / 'tasks' / ('a' * 64) / 'input.txt').parent
        (candidate / 'outside').symlink_to(external, target_is_directory=True)
        age(candidate)
        sweep_storage(root, database.db_path, dry_run=False)
        assert candidate.exists()
    assert list(external.iterdir()) == [external / 'keep.txt']
    assert (external / 'keep.txt').read_bytes() == b'external content'


def test_missing_database_is_not_created_by_dry_run(tmp_path):
    root = tmp_path / 'storage'
    root.mkdir()
    with pytest.raises(FileNotFoundError):
        sweep_storage(root, root / 'state.db')
    assert list(root.iterdir()) == []


@pytest.mark.parametrize('setting,value', [('STORAGE_RETENTION_SECONDS', '0'),
    ('STORAGE_ORPHAN_GRACE_SECONDS', '-1'), ('STORAGE_MAX_BYTES', 'no'),
    ('STORAGE_MIN_FREE_BYTES', '-1'), ('STORAGE_CLEANUP_ENABLED', 'maybe')])
def test_invalid_configuration_rejected(monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=setting):
        StoragePolicy.from_env()


def test_quota_counts_unknown_files_without_deleting_them(store):
    root, _ = store
    path = write(root / 'user.dat', b'x' * 100)
    policy = StoragePolicy(storage_max_bytes=1, storage_min_free_bytes=0)
    with pytest.raises(StorageBudgetExceeded, match='STORAGE_MAX_BYTES'):
        check_storage_budget(root, policy=policy)
    assert path.read_bytes() == b'x' * 100


def test_free_space_reserve_and_pending_write_budget(tmp_path, monkeypatch):
    policy = StoragePolicy(storage_min_free_bytes=100)
    monkeypatch.setattr('src.core.storage_retention.shutil.disk_usage', Mock(return_value=Mock(free=110)))
    check_storage_budget(tmp_path, additional_bytes=10, policy=policy)
    with pytest.raises(StorageBudgetExceeded, match='free disk'):
        check_storage_budget(tmp_path, additional_bytes=11, policy=policy)
    check_storage_budget(tmp_path, policy=replace(policy, storage_min_free_bytes=0))


def test_quota_scan_tolerates_atomic_file_removal(store, monkeypatch):
    from src.core import storage_retention
    root, _ = store
    transient = write(root / '.pending-vanishing')
    original = storage_retention._tree_info
    def scan(path, anchor, **kwargs):
        if path == transient:
            transient.unlink()
            raise FileNotFoundError('concurrent atomic publication')
        return original(path, anchor, **kwargs)
    monkeypatch.setattr(storage_retention, '_tree_info', scan)
    check_storage_budget(root, policy=StoragePolicy(storage_max_bytes=10_000_000, storage_min_free_bytes=0))


def test_crashed_compiler_owner_releases_lease_for_cleanup(store, tmp_path):
    root, database = store
    workspace = write(root / 'output' / '.compile-crashed' / 'result.mp3').parent
    ready = tmp_path / 'ready'
    command = ('from pathlib import Path; import time; '
               'from src.core.cache_io import try_directory_lock; '
               'import sys\n'
               'with try_directory_lock(Path(sys.argv[1])) as acquired:\n'
               '    assert acquired\n'
               '    Path(sys.argv[2]).write_text("ready")\n'
               '    time.sleep(30)\n')
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    process = subprocess.Popen([sys.executable, '-c', command, str(workspace), str(ready)], env=environment)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        age(workspace)
        sweep_storage(root, database.db_path, dry_run=False)
        assert workspace.joinpath('result.mp3').exists()
    finally:
        process.kill()
        process.wait(timeout=5)
    sweep_storage(root, database.db_path, dry_run=False)
    assert not workspace.exists()


@pytest.mark.parametrize('path', ['/api/generate', '/api/resume/task-id'])
def test_full_storage_rejects_before_body_and_releases_admission(path):
    controller = JobController(1, 0)
    app, receive = AsyncMock(), AsyncMock()
    check = Mock(side_effect=StorageBudgetExceeded('Storage budget exceeded'))
    middleware = GenerationRequestLimits(app, lambda: controller, storage_check=check)
    sent = []
    async def send(message):
        sent.append(message)
    asyncio.run(middleware({'type': 'http', 'method': 'POST', 'path': path, 'headers': []}, receive, send))
    assert sent[0]['status'] == 507
    app.assert_not_called()
    receive.assert_not_called()
    assert controller.admission.acquire(False)
    controller.admission.release()


def test_chunk_budget_check_happens_before_paid_call(store, monkeypatch):
    root, _ = store
    monkeypatch.setenv('STORAGE_MAX_BYTES', '1')
    client = Mock(generate_audio=AsyncMock())
    with pytest.raises(StorageBudgetExceeded):
        asyncio.run(generate_chunk_atomic(client, 'text', root / 'chunk.mp3'))
    client.generate_audio.assert_not_called()
    assert not list(root.glob('.pending-*'))


def test_database_symlink_cannot_modify_external_metadata(store, tmp_path):
    root, database = store
    external = TaskDatabase(tmp_path / 'external.db')
    external.create_task('outside')
    linked = root / 'linked.db'
    linked.symlink_to(external.db_path)
    with pytest.raises(ValueError, match='symbolic link'):
        sweep_storage(root, linked, dry_run=False)
    assert external.get_task('outside') is not None
    assert database.get_task('outside') is None


def test_maintenance_command_defaults_to_dry_run_and_requires_apply(store):
    root, database = store
    task_id, cache = job(store, 'Completed')
    environment = {'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'PYTHONIOENCODING': 'utf-8',
                   'STORAGE_CLEANUP_ENABLED': 'true'}
    for name in ('PATH', 'SYSTEMROOT', 'WINDIR'):
        if name in os.environ:
            environment[name] = os.environ[name]
    command = [sys.executable, '-m', 'src.core.storage_retention', '--storage', str(root)]
    before = snapshot(root)
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['dry_run'] is True
    assert snapshot(root) == before
    result = subprocess.run([*command, '--apply'], env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['dry_run'] is False
    assert database.get_task(task_id) is None
    assert not cache.joinpath('chunk_0000.mp3').exists()
