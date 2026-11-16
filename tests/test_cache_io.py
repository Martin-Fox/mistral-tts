import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
from pathlib import Path
import threading
from unittest.mock import Mock

import pytest

from src.core.cache_io import (cache_lock, generate_chunk_atomic, run_blocking_until_done,
                               save_json_atomic, save_text_atomic)


def hold_lock(directory, acquired, release):
    async def run():
        async with cache_lock(Path(directory)):
            acquired.set()
            while not release.is_set():
                await asyncio.sleep(0.02)
    asyncio.run(run())


def update_manifest(directory, start):
    start.wait(5)
    async def run():
        path = Path(directory) / 'manifest.json'
        async with cache_lock(Path(directory)):
            data = json.loads(path.read_text()) if path.exists() else {'completed': []}
            data['completed'].append(multiprocessing.current_process().name)
            await asyncio.sleep(0.05)
            save_json_atomic(path, data)
    asyncio.run(run())


def test_two_processes_preserve_manifest_updates(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    start = ctx.Event()
    workers = [ctx.Process(target=update_manifest, args=(str(tmp_path), start)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        start.set()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert len(json.loads((tmp_path / 'manifest.json').read_text())['completed']) == 2
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


def test_crashed_owner_releases_lock_without_removing_lockfile(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    acquired, release = ctx.Event(), ctx.Event()
    owner = ctx.Process(target=hold_lock, args=(str(tmp_path), acquired, release))
    owner.start()
    try:
        assert acquired.wait(5)
        async def blocked():
            with pytest.raises(TimeoutError):
                async with cache_lock(tmp_path, timeout_seconds=0.1):
                    pytest.fail('lock bypassed')
        asyncio.run(blocked())
        owner.terminate()
        owner.join(5)
        assert not owner.is_alive()
        assert (tmp_path / '.cache.lock').exists()
        async def acquire():
            async with cache_lock(tmp_path, timeout_seconds=1):
                pass
        asyncio.run(acquire())
    finally:
        if owner.is_alive():
            owner.terminate()
            owner.join(5)


def test_other_caches_and_heartbeat_work_while_waiting(tmp_path):
    async def run():
        first, second = tmp_path / 'one', tmp_path / 'two'
        async with cache_lock(first):
            async def wait():
                async with cache_lock(first):
                    return 'acquired'
            waiter = asyncio.create_task(wait())
            await asyncio.sleep(0.02)
            assert not waiter.done()
            async with cache_lock(second, timeout_seconds=0.2):
                assert not waiter.done()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        async with cache_lock(first, timeout_seconds=0.2):
            pass
    asyncio.run(run())


def test_compiler_cancellation_keeps_lock_until_thread_finishes(tmp_path):
    started, finish = threading.Event(), threading.Event()
    def compile_audio():
        started.set()
        assert finish.wait(5)
    async def run():
        async def owner():
            async with cache_lock(tmp_path):
                await run_blocking_until_done(compile_audio)
        task = asyncio.create_task(owner())
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()  # Repeated cancellation must not release the cache early.
            with pytest.raises(TimeoutError):
                async with cache_lock(tmp_path, timeout_seconds=0.1):
                    pytest.fail('reader still running without lock')
            assert not task.done()
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        async with cache_lock(tmp_path, timeout_seconds=0.2):
            pass
    asyncio.run(run())


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('failure', ['exception', 'small', 'cancel'])
def test_partial_chunks_never_replace_published_audio(tmp_path, existing, failure):
    output = tmp_path / 'chunk_0000.mp3'
    if existing:
        output.write_bytes(b'previous-audio' * 100)
    async def generate(text, staged):
        staged.write_bytes(b'small' if failure == 'small' else b'partial-audio' * 100)
        assert output.exists() is existing
        if failure == 'exception':
            raise RuntimeError('interrupted')
        if failure == 'cancel':
            raise asyncio.CancelledError
    client = Mock(generate_audio=generate)
    with pytest.raises((RuntimeError, asyncio.CancelledError)):
        asyncio.run(generate_chunk_atomic(client, 'text', output))
    assert output.exists() is existing
    if existing:
        assert output.read_bytes() == b'previous-audio' * 100
    assert not list(tmp_path.glob('.pending-*'))


def test_successful_chunk_is_published_after_generation(tmp_path):
    output = tmp_path / 'chunk_0000.mp3'
    async def generate(text, staged):
        assert staged != output
        assert staged.suffix == '.mp3'
        staged.write_bytes(b'complete-audio' * 100)
        assert not output.exists()
    asyncio.run(generate_chunk_atomic(Mock(generate_audio=generate), 'text', output))
    assert output.read_bytes() == b'complete-audio' * 100
    assert not list(tmp_path.glob('.pending-*'))


def test_concurrent_text_publications_use_unique_temporary_files(tmp_path, monkeypatch):
    output = tmp_path / 'translation.txt'
    barrier = threading.Barrier(2)
    replace = Path.replace
    temporary_paths = []
    def synchronized_replace(path, destination):
        temporary_paths.append(path)
        barrier.wait(timeout=3)
        return replace(path, destination)
    monkeypatch.setattr(Path, 'replace', synchronized_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(save_text_atomic, output, text) for text in ('first', 'second')]
        for result in results:
            result.result(timeout=5)
    assert temporary_paths[0] != temporary_paths[1]
    assert output.read_text() in ('first', 'second')
    assert not list(tmp_path.glob('.pending-*'))


def test_failed_manifest_publication_preserves_previous_state(tmp_path, monkeypatch):
    output = tmp_path / 'manifest.json'
    save_json_atomic(output, {'completed': ['first']})
    monkeypatch.setattr(Path, 'replace', Mock(side_effect=OSError('write failed')))
    with pytest.raises(OSError):
        save_json_atomic(output, {'completed': ['first', 'second']})
    assert json.loads(output.read_text()) == {'completed': ['first']}
    assert not list(tmp_path.glob('.pending-*'))


def run_cached_pipeline(root, interface, ready, start):
    import os
    import time
    from unittest.mock import AsyncMock
    os.chdir(root)
    if interface == 'cli':
        from src import cli as module
    else:
        from src import web as module
    async def generate(text, path):
        with open('generation.log', 'a') as stream:
            stream.write('generated\n')
        path.write_bytes(b'partial')
        await asyncio.sleep(0.1)
        path.write_bytes(b'complete-audio' * 100)
    def compile_audio(chunks, output):
        content = chunks[0].read_bytes()
        time.sleep(0.1)
        assert chunks[0].read_bytes() == content
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return {}
    client = Mock(model='fake-model')
    client.generate_audio = AsyncMock(side_effect=generate)
    module.get_tts_client = Mock(return_value=client)
    module.AudioCompiler = Mock(return_value=Mock(compile=compile_audio))
    ready.set()
    assert start.wait(10)
    if interface == 'cli':
        runner = module.BooksmithCLI('fake-key')
        asyncio.run(runner.run(Path('book.txt'), Path('shared-voice'), Path('cli-result.mp3')))
    else:
        module.db.create_task('web-task')
        asyncio.run(module.run_generation_pipeline(
            'web-task', 'fake-key', 'shared source', None, None, 'shared-voice', None,
            None, None, 'web-result.mp3'))
        assert module.db.get_task('web-task')['completed']


def test_cli_and_web_processes_share_generation_without_lost_updates(tmp_path):
    (tmp_path / 'book.txt').write_text('shared source')
    ctx = multiprocessing.get_context('spawn')
    start = ctx.Event()
    ready = [ctx.Event(), ctx.Event()]
    workers = [ctx.Process(target=run_cached_pipeline,
                          args=(str(tmp_path), interface, signal, start))
               for interface, signal in zip(('cli', 'web'), ready)]
    try:
        for worker in workers:
            worker.start()
        assert all(signal.wait(10) for signal in ready)
        start.set()
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
        assert (tmp_path / 'generation.log').read_text().splitlines() == ['generated']
        manifests = list((tmp_path / 'storage/cache').glob('v2_*/manifest.json'))
        assert len(manifests) == 1
        assert json.loads(manifests[0].read_text())['completed'] == ['chunk_0000.mp3']
        assert (tmp_path / 'cli-result.mp3').read_bytes() == b'complete-audio' * 100
        assert (tmp_path / 'storage/output/web-task_web-result.mp3').read_bytes() == b'complete-audio' * 100
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
