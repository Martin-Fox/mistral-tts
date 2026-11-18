import asyncio
import io
import os
from pathlib import Path
import subprocess
import struct
import sys
import uuid
import wave
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
import pytest

from src import web
from src.api.mistral_client import MistralTTSClient
from src.core.process_runner import run_process_async
from src.core.resource_limits import ResourceLimitExceeded, ResourceLimits
from src.core.task_store import save_job
from src.core.voice_reference import prepare_reference, reference_command, reference_environment


def make_reference(path, seconds=1, codec=None):
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'sine=duration={seconds}']
    if codec:
        command += ['-c:a', codec]
    subprocess.run([*command, str(path)], check=True, capture_output=True, timeout=10)


@pytest.mark.parametrize('suffix', ['.wav', '.mp3'])
def test_supported_reference_normalizes_without_modifying_source(tmp_path, suffix):
    source = tmp_path / ('sample' + suffix)
    make_reference(source)
    original = source.read_bytes()
    normalized = asyncio.run(prepare_reference(source))
    assert source.read_bytes() == original
    with wave.open(io.BytesIO(normalized)) as audio:
        assert (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) == (1, 24000, 2)
        assert 0 < audio.getnframes() <= 24000 * 2


@pytest.mark.parametrize('content', [b'caff' + b'\0' * 100, b'#EXTM3U\nhttp://127.0.0.1/test',
                                   b'ffconcat version 1.0\nfile /etc/passwd', b'RIFFxxxxWAVE'])
def test_renamed_containers_and_playlists_never_reach_decoder(tmp_path, monkeypatch, content):
    source = tmp_path / 'sample.mp3'
    source.write_bytes(content)
    runner = AsyncMock()
    monkeypatch.setattr('src.core.voice_reference.run_process_async', runner)
    with pytest.raises(ValueError, match='MP3 or PCM WAV'):
        asyncio.run(prepare_reference(source))
    runner.assert_not_called()


def test_wav_with_unsupported_codec_is_rejected(tmp_path):
    source = tmp_path / 'sample.wav'
    # A valid mono IMA ADPCM block, without requiring an encoder that the
    # restricted runtime intentionally does not build.
    fmt = struct.pack('<HHIIHHHH', 17, 1, 8000, 4055, 256, 4, 2, 505)
    contents = b'fmt ' + struct.pack('<I', len(fmt)) + fmt
    contents += b'fact' + struct.pack('<II', 4, 505)
    contents += b'data' + struct.pack('<I', 256) + bytes(256)
    source.write_bytes(b'RIFF' + struct.pack('<I', len(contents) + 4) + b'WAVE' + contents)
    with pytest.raises(ValueError, match='could not be decoded'):
        asyncio.run(prepare_reference(source))


def test_overlong_reference_is_rejected_instead_of_truncated(tmp_path, monkeypatch):
    source = tmp_path / 'sample.wav'
    make_reference(source, seconds=3)
    original = source.read_bytes()
    monkeypatch.setenv('MAX_VOICE_SECONDS', '1')
    with pytest.raises(ResourceLimitExceeded, match='MAX_VOICE_SECONDS'):
        asyncio.run(prepare_reference(source))
    assert source.read_bytes() == original


def test_decoded_byte_budget_cannot_be_bypassed_by_compressed_input(tmp_path, monkeypatch):
    source = tmp_path / 'sample.mp3'
    make_reference(source, seconds=2)
    assert source.stat().st_size < 20000
    monkeypatch.setenv('MAX_VOICE_UPLOAD_BYTES', '20000')
    with pytest.raises((ResourceLimitExceeded, ValueError)):
        asyncio.run(prepare_reference(source))


def test_reference_process_has_no_application_credentials_or_proxy_settings(monkeypatch, tmp_path):
    for name in ('MISTRAL_API_KEY', 'OPENAI_API_KEY', 'APP_PASSWORD', 'HTTP_PROXY',
                 'HTTPS_PROXY', 'FFREPORT', 'LD_PRELOAD', 'BOOKSMITH_ENV_FILE'):
        monkeypatch.setenv(name, 'synthetic-secret-do-not-inherit')
    environment = reference_environment(tmp_path)
    assert 'synthetic-secret-do-not-inherit' not in environment.values()
    assert environment['HOME'] == str(tmp_path)
    assert environment['TMPDIR'] == str(tmp_path)


def test_reference_command_forces_formats_codecs_protocols_and_output_budgets():
    command = reference_command('/bin/ffmpeg', Path('/input.wav'), Path('/reference.wav'),
                                'wav', ResourceLimits(), 120, 100000)
    assert command[command.index('-protocol_whitelist') + 1] == 'file'
    assert command[command.index('-format_whitelist') + 1] == 'wav'
    codecs = command[command.index('-codec_whitelist') + 1]
    assert 'adpcm' not in codecs and 'mace' not in codecs
    assert command[command.index('-t') + 1] == '31'
    assert command[command.index('-fs') + 1] == '100000'
    if sys.platform.startswith('linux'):
        assert '--as=536870912' in command
        assert '--fsize=100000' in command
        assert '--cpu=120' in command


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux prlimit')
def test_missing_prlimit_fails_closed(monkeypatch):
    monkeypatch.setattr('src.core.voice_reference.shutil.which', lambda name: None)
    with pytest.raises(RuntimeError, match='prlimit'):
        reference_command('/bin/ffmpeg', Path('/input.wav'), Path('/reference.wav'),
                          'wav', ResourceLimits(), 120, 100000)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux address-space limit')
def test_hard_memory_budget_applies_to_real_decoder(tmp_path, monkeypatch):
    source = tmp_path / 'sample.wav'
    make_reference(source)
    monkeypatch.setenv('MAX_VOICE_PROCESS_MEMORY_BYTES', '1048576')
    with pytest.raises(ValueError, match='could not be decoded'):
        asyncio.run(prepare_reference(source))


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_noisy_process_is_killed_and_reaped_with_bounded_capture(tmp_path, stream):
    pid_file = tmp_path / 'pid'
    code = ('import os,sys; open(sys.argv[1],"w").write(str(os.getpid())); '
            f'stream=sys.{stream}.buffer\nwhile True: stream.write(b"x"*4096); stream.flush()')
    with pytest.raises(ResourceLimitExceeded, match='diagnostic byte budget'):
        asyncio.run(run_process_async([sys.executable, '-c', code, str(pid_file)],
                                     timeout=5, max_output_bytes=4096))
    assert pid_file.exists()
    if os.name == 'posix':
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


def test_rejected_sample_clears_old_voice_and_cannot_fall_back(tmp_path):
    source = tmp_path / 'sample.mp3'
    source.write_bytes(b'caff' + b'\0' * 100)
    client = MistralTTSClient('synthetic-key')
    client.voice_sample_path, client.voice_sample_bytes = source, b'old-reference'
    client.voice_id = 'old-voice'
    with pytest.raises(ValueError):
        asyncio.run(client.clone_voice(source))
    assert client.voice_sample_path is None and client.voice_sample_bytes is None
    assert client.voice_id is None


def test_raw_reference_path_cannot_bypass_validation(tmp_path):
    source = tmp_path / 'sample.mp3'
    source.write_bytes(b'original-must-not-be-sent')
    client = MistralTTSClient('synthetic-key')
    client.voice_sample_path = source
    speech = AsyncMock()
    client.client = Mock(audio=Mock(speech=Mock(complete_async=speech)))
    with pytest.raises(ValueError, match='has not passed validation'):
        asyncio.run(client.generate_audio('hello', tmp_path / 'chunk.mp3'))
    speech.assert_not_called()


@pytest.mark.parametrize('filename', ['book.mobi', 'BOOK.MOBI'])
def test_web_mobi_is_rejected_before_parser_or_paid_work(authenticated_web, monkeypatch, filename):
    pipeline, saved = AsyncMock(), Mock()
    monkeypatch.setattr(web, 'run_generation_pipeline', pipeline)
    monkeypatch.setattr(web, 'save_job', saved)
    parser = Mock(side_effect=AssertionError('MOBI parser must not run'))
    monkeypatch.setattr('src.core.epub_parser.read_input_text', parser)
    response = TestClient(authenticated_web, headers={'X-Requested-With': 'Booksmith'}, cookies={'session_id': 'session-id'}).post(
        '/api/generate', data={'api_key': 'synthetic-key'}, files={'text_file': (filename, b'fake')})
    assert response.status_code == 415
    pipeline.assert_not_called()
    saved.assert_not_called()
    parser.assert_not_called()


def test_web_mobi_resume_is_rejected_without_claiming_job(authenticated_web, monkeypatch):
    task_id = str(uuid.uuid4())
    save_job(task_id, {'engine': 'mistral', 'text_file_data': ('book.mobi', b'fake')})
    web.db.create_task(task_id)
    web.db.update_task(task_id, status='Interrupted')
    claim = Mock()
    monkeypatch.setattr(web.db, 'claim_resume', claim)
    response = TestClient(authenticated_web, headers={'X-Requested-With': 'Booksmith'}, cookies={'session_id': 'session-id'}).post(
        '/api/resume/' + task_id, data={'api_key': 'synthetic-key'})
    assert response.status_code == 415
    claim.assert_not_called()
    assert web.db.get_task(task_id)['status'] == 'Interrupted'


def test_web_invalid_voice_rejected_before_translation_or_snapshot(authenticated_web, monkeypatch):
    pipeline, saved = AsyncMock(), Mock()
    monkeypatch.setattr(web, 'run_generation_pipeline', pipeline)
    monkeypatch.setattr(web, 'save_job', saved)
    response = TestClient(authenticated_web, headers={'X-Requested-With': 'Booksmith'}, cookies={'session_id': 'session-id'}).post(
        '/api/generate', data={'api_key': 'synthetic-key', 'text_content': 'hello', 'target_lang': 'Polish'},
        files={'voice_file': ('sample.wav', b'not-wave-audio')})
    assert response.status_code == 400
    pipeline.assert_not_called()
    saved.assert_not_called()
