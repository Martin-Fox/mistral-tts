import asyncio
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.process_runner import process_budget, run_process, run_process_async
from src.api.mistral_client import MistralTTSClient
from test_audio_publication import make_audio


def test_duration_budgets_are_scaled_and_capped(monkeypatch):
    for name in ('AUDIO_PROBE_TIMEOUT_SECONDS', 'AUDIO_PROCESS_TIMEOUT_SECONDS',
                 'AUDIO_TIMEOUT_FACTOR', 'AUDIO_MAX_TIMEOUT_SECONDS'):
        monkeypatch.delenv(name, raising=False)
    assert process_budget(probe=True) == 30
    assert process_budget(36000, probe=True) == 3630
    assert process_budget(1e8) == 7200
    assert process_budget(float('nan')) == 120


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', 'bad'])
def test_invalid_timeout_configuration_is_rejected(monkeypatch, value):
    monkeypatch.setenv('AUDIO_PROCESS_TIMEOUT_SECONDS', value)
    with pytest.raises(ValueError):
        process_budget()


def assert_reaped(pid_file):
    if os.name == 'posix':
        pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_sync_timeout_kills_and_reaps_child(tmp_path):
    pid_file = tmp_path / 'pid'
    command = [sys.executable, '-c',
               'import os,time,sys; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)', str(pid_file)]
    with pytest.raises(subprocess.TimeoutExpired):
        run_process(command, timeout=0.5)
    assert pid_file.exists()
    assert_reaped(pid_file)


@pytest.mark.parametrize('cancel', [False, True])
def test_async_timeout_and_cancellation_reap_child(tmp_path, cancel):
    pid_file = tmp_path / 'pid'
    command = [sys.executable, '-c',
               'import os,time,sys; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)', str(pid_file)]
    async def run():
        task = asyncio.create_task(run_process_async(command, timeout=5 if cancel else 0.5))
        if cancel:
            for _ in range(200):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.01)
            assert pid_file.exists()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else asyncio.TimeoutError):
            await task
    asyncio.run(run())
    assert_reaped(pid_file)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX signal handling')
def test_stubborn_child_is_killed_even_after_repeated_cancellation(tmp_path):
    pid_file = tmp_path / 'pid'
    command = [sys.executable, '-c',
               'import os,time,sys,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
               'open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)', str(pid_file)]
    async def run():
        task = asyncio.create_task(run_process_async(command, timeout=10))
        for _ in range(200):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    asyncio.run(run())
    assert_reaped(pid_file)


def test_failed_async_process_retains_stderr():
    async def run():
        with pytest.raises(subprocess.CalledProcessError) as error:
            await run_process_async([sys.executable, '-c',
                                     'import sys;sys.stderr.write("diagnostic");sys.exit(3)'], timeout=5)
        assert error.value.stderr == b'diagnostic'
    asyncio.run(run())


def test_real_denoising_preserves_original_and_uses_processed_bytes(tmp_path, monkeypatch):
    original = tmp_path / 'voice.wav'
    make_audio(original)
    original_bytes = original.read_bytes()
    directories = []
    factory = tempfile.TemporaryDirectory
    def temporary(**kwargs):
        result = factory(**kwargs)
        directories.append(Path(result.name))
        return result
    monkeypatch.setattr('src.core.voice_reference.tempfile.TemporaryDirectory', temporary)
    client = MistralTTSClient('fake-key')
    async def run():
        await client.clone_voice(original)
        assert client.voice_sample_bytes
        response = Mock(audio_data=None, audio=b'x' * 200)
        speech = AsyncMock(return_value=response)
        client.client = Mock(audio=Mock(speech=Mock(complete_async=speech)))
        monkeypatch.setattr('src.api.mistral_client.run_process_async',
                            AsyncMock(return_value=Mock(stdout=b'2.5\n')))
        await client.generate_audio('test', tmp_path / 'chunk.mp3', retry_count=1)
        assert base64.b64decode(speech.call_args.kwargs['ref_audio']) == client.voice_sample_bytes
    asyncio.run(run())
    assert original.read_bytes() == original_bytes
    assert all(not path.exists() for path in directories)


def test_denoising_error_rejects_reference_without_fallback(tmp_path, monkeypatch):
    original = tmp_path / 'voice.wav'
    make_audio(original)
    before = original.read_bytes()
    monkeypatch.setattr('src.core.voice_reference.run_process_async', AsyncMock(
        side_effect=subprocess.CalledProcessError(1, ['ffmpeg'], stderr=b'filter diagnostic')))
    client = MistralTTSClient('fake-key')
    with pytest.raises(ValueError, match='could not be decoded'):
        asyncio.run(client.clone_voice(original))
    assert original.read_bytes() == before
    assert client.voice_sample_bytes is None
    assert client.voice_sample_path is None


def test_cancelling_threaded_processing_stops_child(tmp_path):
    from src.core.cache_io import run_blocking_until_done
    pid_file = tmp_path / 'pid'
    command = [sys.executable, '-c',
               'import os,time,sys;open(sys.argv[1],"w").write(str(os.getpid()));time.sleep(30)', str(pid_file)]
    async def run():
        task = asyncio.create_task(run_blocking_until_done(lambda: run_process(command, timeout=30)))
        for _ in range(200):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    asyncio.run(run())
    assert_reaped(pid_file)


def test_tui_compilation_does_not_block_event_loop(tmp_path, monkeypatch):
    import threading
    from src import tui
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'book.txt'
    source.write_text('text')
    app = tui.BooksmithTUI()
    app.log_message = Mock()
    app.query_one = Mock()
    tts = Mock()
    tts.model = 'test-model'
    async def generate(text, path):
        path.write_bytes(b'valid fake audio' * 20)
    tts.generate_audio = AsyncMock(side_effect=generate)
    monkeypatch.setattr(tui, 'get_tts_client', Mock(return_value=tts))
    started, finish = threading.Event(), threading.Event()
    def compile_audio(*args):
        started.set()
        assert finish.wait(3)
        return {}
    monkeypatch.setattr(tui, 'AudioCompiler', Mock(return_value=Mock(compile=compile_audio)))
    async def run():
        task = asyncio.create_task(app.process_book(str(source), '', 'voice',
                                                   str(tmp_path / 'book.mp3'), 'fake-key'))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            assert not task.done()  # The UI/event loop remains runnable during compilation.
        finally:
            finish.set()
            await task
    asyncio.run(run())


def test_cancelling_denoising_cleans_private_workspace(tmp_path, monkeypatch):
    original = tmp_path / 'voice.wav'
    make_audio(original)
    before = original.read_bytes()
    directories = []
    factory = tempfile.TemporaryDirectory
    def temporary(**kwargs):
        directory = factory(**kwargs)
        directories.append(Path(directory.name))
        return directory
    monkeypatch.setattr('src.core.voice_reference.tempfile.TemporaryDirectory', temporary)
    monkeypatch.setattr('src.core.voice_reference.run_process_async',
                        AsyncMock(side_effect=asyncio.CancelledError))
    client = MistralTTSClient('fake-key')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.clone_voice(original))
    assert directories and all(not directory.exists() for directory in directories)
    assert original.read_bytes() == before
