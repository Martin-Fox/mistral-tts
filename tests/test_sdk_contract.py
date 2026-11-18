"""Exercise the actual pinned SDK serializer/parser with an offline HTTP transport."""
import base64
import json
import os
import subprocess
from unittest.mock import AsyncMock, Mock

import httpx
from mistralai.client import Mistral
import pytest

from src.api.mistral_client import MistralTTSClient
from src.api.retry import APIResponseError


def install_transport(monkeypatch, http):
    def create(**kwargs):
        assert kwargs['retry_config'] is None
        return Mistral(async_client=http, **kwargs)
    monkeypatch.setattr('src.api.mistral_client.Mistral', create)


@pytest.mark.anyio
@pytest.mark.parametrize('reference', [False, True])
async def test_real_sdk_serializes_preset_and_reference_tts(monkeypatch, tmp_path, reference):
    payloads = []
    audio = b'fake-generated-audio' * 30
    def handle(request):
        assert request.method == 'POST' and request.url.path == '/v1/audio/speech'
        assert request.headers['Authorization'] == 'Bearer synthetic-key'
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={'audio_data': base64.b64encode(audio).decode()})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        install_transport(monkeypatch, http)
        client = MistralTTSClient('synthetic-key')
        if reference:
            # The normal pipeline obtains these validated bytes from clone_voice;
            # isolate the wire contract from FFmpeg's already-tested normalization.
            source = tmp_path / 'reference.wav'
            source.write_bytes(b'validated-reference-placeholder')
            normalized = b'normalized PCM WAV placeholder'
            monkeypatch.setattr('src.api.mistral_client.prepare_reference', AsyncMock(return_value=normalized))
            await client.clone_voice(source)
        else:
            client.set_voice_id('en_paul_neutral')
        monkeypatch.setattr('src.api.mistral_client.run_process_async',
                            AsyncMock(return_value=Mock(stdout=b'1.5\n')))
        destination = tmp_path / 'chunk.mp3'
        await client.generate_audio('Hello world.', destination, retry_count=1)
        assert destination.read_bytes() == audio
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload['input'] == 'Hello world.' and payload['model'] == 'voxtral-mini-tts-2603'
    assert payload['response_format'] == 'mp3' and payload.get('stream') is False
    if reference:
        assert base64.b64decode(payload['ref_audio']) == normalized
        assert not payload.get('voice_id')
    else:
        assert payload['voice_id'] == 'en_paul_neutral' and not payload.get('ref_audio')


@pytest.mark.anyio
async def test_real_sdk_translation_and_json_batch_format(monkeypatch):
    payloads = []
    def handle(request):
        assert request.url.path == '/v1/chat/completions'
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'offline', 'object': 'chat.completion', 'model': 'translation-model', 'created': 1,
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'Cześć.'}}],
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        install_transport(monkeypatch, http)
        client = MistralTTSClient('synthetic-key', translation_model='translation-model')
        assert await client.translate_text('Hello.', 'English', 'Polish', retry_count=1) == 'Cześć.'
        await client._translation_request(model='translation-model',
            messages=[{'role': 'user', 'content': 'Batch'}], response_format={'type': 'json_object'})
    assert payloads[0]['model'] == 'translation-model'
    assert 'Hello.' in payloads[0]['messages'][0]['content']
    assert payloads[1]['response_format'] == {'type': 'json_object'}


@pytest.mark.anyio
async def test_real_sdk_model_and_voice_lists_include_optional_slug(monkeypatch):
    def handle(request):
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'object': 'list', 'data': [
                {'id': 'translation-model', 'type': 'base', 'capabilities': {'completion_chat': True}},
            ]})
        assert request.url.path == '/v1/audio/voices'
        common = {'created_at': '2026-11-18T00:00:00Z', 'user_id': None, 'type': 'preset'}
        return httpx.Response(200, json={'total': 2, 'page': 0, 'page_size': 10, 'total_pages': 1,
            'items': [{'name': 'Named', 'id': 'voice-1', 'slug': 'en_paul_neutral', **common},
                      {'name': 'Without slug', 'id': 'voice-2', **common}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        install_transport(monkeypatch, http)
        client = MistralTTSClient('synthetic-key')
        assert await client.list_models(retry_count=1) == ['translation-model']
        assert await client.list_voices(retry_count=1) == [
            {'id': 'en_paul_neutral', 'name': 'Named'}, {'id': 'voice-2', 'name': 'Without slug'}]


@pytest.mark.anyio
async def test_real_sdk_does_not_add_hidden_retries_or_disclose_error_body(monkeypatch, tmp_path):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(503, json={'message': 'provider-body-must-not-leak'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        install_transport(monkeypatch, http)
        client = MistralTTSClient('synthetic-key')
        client.set_voice_id('en_paul_neutral')
        with pytest.raises(APIResponseError) as failure:
            await client.generate_audio('Hello.', tmp_path / 'chunk.mp3', retry_count=1)
        assert failure.value.status_code == 503
        assert 'provider-body-must-not-leak' not in str(failure.value)
        assert 'synthetic-key' not in str(failure.value)
    assert len(requests) == 1


def test_native_build_rejects_modified_source_archive_before_compilation(tmp_path):
    import shutil
    from pathlib import Path
    if os.name != 'posix' or not shutil.which('sh') or not shutil.which('sha256sum'):
        pytest.skip('POSIX native build helper')
    source = tmp_path / 'modified.tar.xz'
    source.write_bytes(b'not the approved release')
    prefix = tmp_path / 'install'
    script = Path(__file__).resolve().parents[1] / 'scripts/build_ffmpeg.sh'
    result = subprocess.run(['sh', str(script), str(source), str(prefix)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and 'FAILED' in result.stdout
    assert not prefix.exists()
