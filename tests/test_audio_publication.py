import asyncio
from pathlib import Path
import subprocess
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.audio_compiler import AudioCompiler
from src.core.task_db import TaskDatabase
from src import web


def make_audio(path, frequency=440):
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
        f'sine=frequency={frequency}:duration=1', '-q:a', '9', str(path)
    ], check=True, capture_output=True)


@pytest.mark.parametrize('extension', ['.mp3', '.wav', '.m4b'])
def test_real_ffmpeg_handles_quoted_unicode_paths(tmp_path, extension):
    folder = tmp_path / "reader's książki with spaces"
    folder.mkdir()
    chunk = folder / "chapter's first.mp3"
    make_audio(chunk)
    output = folder / f"book's output{extension}"
    meta = AudioCompiler().compile([chunk], output)
    assert output.exists()
    assert meta['output_path'] == output
    assert meta['output_duration'] > 1
    assert not list(folder.glob('.compile-*'))


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('fail_validation', [False, True])
def test_output_is_published_only_after_validation(tmp_path, monkeypatch, existing, fail_validation):
    chunk = tmp_path / 'chunk.mp3'
    make_audio(chunk)
    output = tmp_path / 'book.mp3'
    old = b'previous-result'
    if existing:
        output.write_bytes(old)
    compiler = AudioCompiler()
    probe = compiler._probe_duration
    checked = []

    def validate(path):
        if path != chunk:
            checked.append(path)
            assert output.exists() is existing
            if existing:
                assert output.read_bytes() == old
            if fail_validation:
                raise RuntimeError('simulated validation failure')
        return probe(path)

    monkeypatch.setattr(compiler, '_probe_duration', validate)
    if fail_validation:
        with pytest.raises(RuntimeError, match='simulated validation failure'):
            compiler.compile([chunk], output)
        assert output.exists() is existing
        if existing:
            assert output.read_bytes() == old
    else:
        compiler.compile([chunk], output)
        assert output.read_bytes() != old
    assert checked
    assert not list(tmp_path.glob('.compile-*'))


@pytest.mark.parametrize('stage', ['silence', 'ffmpeg', 'replace'])
def test_failure_cleans_staging_and_preserves_existing_output(tmp_path, monkeypatch, stage):
    chunk = tmp_path / 'chunk.mp3'
    make_audio(chunk)
    output = tmp_path / 'book.mp3'
    output.write_bytes(b'previous-result')
    compiler = AudioCompiler()
    if stage == 'silence':
        def fail_silence(path, **kwargs):
            path.write_bytes(b'partial-silence')
            raise RuntimeError('silence failure')
        monkeypatch.setattr(compiler, '_generate_silence', fail_silence)
    elif stage == 'ffmpeg':
        original_run = subprocess.run
        def fail_compile(cmd, **kwargs):
            if 'concat' in cmd:
                Path(cmd[-1]).write_bytes(b'partial-output')
                raise subprocess.CalledProcessError(1, cmd)
            return original_run(cmd, **kwargs)
        monkeypatch.setattr(subprocess, 'run', fail_compile)
    else:
        monkeypatch.setattr(Path, 'replace', Mock(side_effect=OSError('replace failure')))
    with pytest.raises((RuntimeError, subprocess.CalledProcessError, OSError)):
        compiler.compile([chunk], output)
    assert output.read_bytes() == b'previous-result'
    assert not list(tmp_path.glob('.compile-*'))


def test_concat_rejects_line_break_injection(tmp_path):
    with pytest.raises(ValueError, match='line breaks'):
        AudioCompiler._concat_entry(tmp_path / "audio.mp3\nfile 'other.mp3'")


@pytest.fixture
def isolated_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database = TaskDatabase(tmp_path / 'state.db')
    monkeypatch.setattr(web, 'db', database)
    monkeypatch.setattr(web.global_log_handler, 'database', database)
    tts = Mock()
    tts.model = 'fake-tts-model'

    async def generate(text, path):
        await asyncio.to_thread(make_audio, path, 440 if text == 'first book' else 880)

    tts.generate_audio = AsyncMock(side_effect=generate)
    monkeypatch.setattr(web, 'get_tts_client', Mock(return_value=tts))

    async def run(task, text, filename="audiobook.mp3"):
        database.create_task(task)
        await web.run_generation_pipeline(
            task, 'fake-key', text, None, None, 'voice', None,
            None, None, filename,
        )
        return database.get_task(task)

    return run


def test_parallel_web_tasks_keep_separate_downloadable_results(isolated_pipeline):
    async def both():
        return await asyncio.gather(
            isolated_pipeline('task-one', 'first book'),
            isolated_pipeline('task-two', 'second book'),
        )
    first, second = asyncio.run(both())
    assert first['completed'] and second['completed']
    assert first['audio_file'] != second['audio_file']
    one = Path('storage/output') / first['audio_file']
    two = Path('storage/output') / second['audio_file']
    assert one.read_bytes() != two.read_bytes()
    assert Path(web.get_audio(first['audio_file']).path) == one.resolve()
    assert Path(web.get_audio(second['audio_file']).path) == two.resolve()
    assert not Path('storage/output/audiobook.mp3').exists()
    assert not list(Path('storage/output').glob('.compile-*'))


def test_failed_web_compilation_does_not_publish_result(isolated_pipeline, monkeypatch):
    compiler = Mock()
    compiler.compile.side_effect = RuntimeError('simulated compilation failure')
    monkeypatch.setattr(web, 'AudioCompiler', Mock(return_value=compiler))
    task = asyncio.run(isolated_pipeline('task-failed', 'first book'))
    assert task['status'] == 'Failed'
    assert not task['completed']
    assert task['audio_file'] is None
    assert not list(Path('storage/output').glob('*.mp3'))


def test_web_keeps_long_unicode_output_names_within_filesystem_limit(isolated_pipeline):
    task = asyncio.run(isolated_pipeline('12345678-1234-1234-1234-123456789012',
                                        'first book', 'ż' * 110 + '.mp3'))
    assert task['completed']
    assert len(task['audio_file'].encode('utf-8')) <= 255
    assert (Path('storage/output') / task['audio_file']).exists()


def test_same_cache_web_tasks_generate_once_and_keep_two_outputs(isolated_pipeline):
    async def both():
        return await asyncio.gather(
            isolated_pipeline('same-one', 'first book'),
            isolated_pipeline('same-two', 'first book'),
        )
    first, second = asyncio.run(both())
    assert first['completed'] and second['completed']
    assert first['audio_file'] != second['audio_file']
    assert web.get_tts_client.return_value.generate_audio.await_count == 1
    one = Path('storage/output') / first['audio_file']
    two = Path('storage/output') / second['audio_file']
    assert one.read_bytes() == two.read_bytes()
