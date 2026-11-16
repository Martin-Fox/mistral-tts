import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import AsyncMock, Mock

import pytest

from src.api.base_client import BaseTTSClient
from src.api.factory import get_tts_client
from src.core.cache_io import cache_lock
from src.core.pipeline import prepare_text, run_pipeline, VoiceInput
from src.core.text_splitter import TextSplitter
from src.core.cache_identity import get_cache_key, hash_sample_file


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'book.txt'
    source.write_text('First sentence. Second sentence. Trailing text', encoding='utf-8')
    return source, tmp_path / 'book.mp3'


@pytest.mark.parametrize('engine', ['mistral', 'openai'])
def test_engine_contract_preserves_segment_order_output_and_cache(setup, engine):
    source, output = setup
    client = get_tts_client(engine, 'dummy-key')
    voice = 'alloy' if engine == 'openai' else 'en_paul_neutral'
    events, order, paths = [], [], []
    async def generate(text, path):
        order.append(text)
        path.write_bytes(text.encode() + b'\0' + b'~' * 200)
    client.generate_audio = AsyncMock(side_effect=generate)
    def compile_audio(chunks, destination):
        paths[:] = chunks
        texts = [path.read_bytes().split(b'\0')[0].decode() for path in chunks]
        assert texts == order
        destination.write_text('|'.join(texts), encoding='utf-8')
        return {'total_chunks': len(chunks)}
    compiler = Mock(compile=Mock(side_effect=compile_audio))
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter(20), progress=events.append)
        result = await run_pipeline(prepared, client=client, engine=engine, voice=VoiceInput(voice),
                                    output_path=output, compiler_factory=lambda: compiler, progress=events.append)
        assert result.compilation['total_chunks'] == len(prepared.chunks)
        assert output.read_text() == '|'.join(prepared.chunks)
        assert client.voice_id == voice
        assert paths == [result.cache_dir / f'chunk_{i:04d}.mp3' for i in range(len(paths))]
        await run_pipeline(prepared, client=client, engine=engine, voice=VoiceInput(voice),
                           output_path=output, compiler_factory=lambda: compiler)
        assert client.generate_audio.await_count == len(prepared.chunks)
    asyncio.run(run())
    stages = [event.stage for event in events]
    assert stages[:5] == ['Reading Text', 'Splitting Text', 'Text Ready', 'Configuring Voice', 'Waiting for Cache']
    assert stages[-1] == 'Compiling Audiobook'
    assert [event.current for event in events if event.stage == 'Chunk Ready'] == list(range(1, len(order) + 1))


def test_translation_adapter_uses_frozen_model_and_utf8_output(setup, monkeypatch):
    source, _ = setup
    source.write_bytes('żółć'.encode('cp1250'))
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'cp1250')
    monkeypatch.setattr('src.core.pipeline.get_translation_model', lambda: 'model-before')
    translated = source.with_name('translated.txt')
    translated.write_text('Zażółć gęślą jaźń', encoding='utf-8')
    async def translate(path, original_lang, target, model):
        assert (path, original_lang, target, model) == (source, 'English', 'Polish', 'model-before')
        monkeypatch.setattr('src.core.pipeline.get_translation_model', lambda: 'model-after')
        return translated
    prepared = asyncio.run(prepare_text(source, splitter=TextSplitter(), target_lang='Polish', translate=translate))
    assert prepared.original == 'żółć'
    assert prepared.chunks == ['Zażółć gęślą jaźń']
    assert prepared.translation_model == 'model-before'


def test_generation_failure_preserves_completed_segments_and_previous_output(setup):
    source, output = setup
    output.write_bytes(b'previous complete output')
    compiler = Mock()
    seen = []
    async def generate(text, path):
        seen.append(text)
        if len(seen) == 2:
            raise RuntimeError('failed second chunk')
        path.write_bytes(b'valid audio' * 30)
    client = Mock(model='test-model', generate_audio=generate)
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter(20))
        with pytest.raises(RuntimeError, match='second chunk'):
            await run_pipeline(prepared, client=client, engine='mistral', voice=VoiceInput(),
                               output_path=output, compiler_factory=lambda: compiler)
        manifest, = Path('storage/cache').glob('*/manifest.json')
        assert json.loads(manifest.read_text())['completed'] == ['chunk_0000.mp3']
        async with cache_lock(manifest.parent, timeout_seconds=0.1):
            pass
    asyncio.run(run())
    compiler.compile.assert_not_called()
    assert output.read_bytes() == b'previous complete output'


def test_observer_failure_stops_before_paid_generation_and_releases_cache(setup):
    source, output = setup
    client = Mock(model='test-model', generate_audio=AsyncMock())
    pinned = []
    def report(event):
        if event.stage == 'Generating Chunk':
            raise RuntimeError('progress persistence failed')
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter())
        with pytest.raises(RuntimeError, match='persistence'):
            await run_pipeline(prepared, client=client, engine='mistral', voice=VoiceInput(),
                               output_path=output, compiler_factory=Mock(), progress=report, cache_ready=pinned.append)
        async with cache_lock(pinned[0], timeout_seconds=0.1):
            pass
    asyncio.run(run())
    client.generate_audio.assert_not_called()
    assert not output.exists()


def test_cancelled_pipeline_keeps_cache_locked_until_compiler_thread_stops(setup):
    source, output = setup
    started, finish = threading.Event(), threading.Event()
    def compile_audio(*args):
        started.set()
        assert finish.wait(5)
        return {}
    async def generate(text, path):
        path.write_bytes(b'valid audio' * 30)
    client = Mock(model='test-model', generate_audio=generate)
    pinned = []
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter())
        task = asyncio.create_task(run_pipeline(
            prepared, client=client, engine='mistral', voice=VoiceInput(), output_path=output,
            compiler_factory=lambda: Mock(compile=compile_audio), cache_ready=pinned.append))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(TimeoutError):
                async with cache_lock(pinned[0], timeout_seconds=0.1):
                    pytest.fail('Compiler is still reading chunks')
            assert not task.done()
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        async with cache_lock(pinned[0], timeout_seconds=0.1):
            pass
    asyncio.run(run())


def test_core_import_does_not_load_web_terminal_frameworks_or_provider_sdk(tmp_path):
    environment = dict(os.environ)
    command = ('import sys; import src.core.pipeline; '
               'assert all(name not in sys.modules for name in ("fastapi", "textual", "mistralai", "openai"))')
    result = subprocess.run([sys.executable, '-c', command], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_client_contract_requires_explicit_voice_selection():
    class IncompleteClient(BaseTTSClient):
        async def generate_audio(self, *args, **kwargs):
            pass
        async def list_voices(self, *args, **kwargs):
            return []
        async def clone_voice(self, *args, **kwargs):
            return ''
    with pytest.raises(TypeError, match='set_voice_id'):
        IncompleteClient('dummy-key')


def test_reference_voice_uses_original_and_processed_fingerprints(setup):
    source, output = setup
    sample = source.with_name('reference.wav')
    sample.write_bytes(b'original reference')
    client = Mock(model='test-model')
    async def clone(path):
        assert path == sample
        client.voice_sample_bytes = b'processed reference'
    async def generate(text, path):
        path.write_bytes(b'valid fake audio' * 20)
    client.clone_voice = AsyncMock(side_effect=clone)
    client.generate_audio = generate
    def compile_audio(paths, destination):
        destination.write_bytes(b'compiled output')
        return {}
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter())
        result = await run_pipeline(prepared, client=client, engine='mistral', voice=VoiceInput(reference=sample),
                                    output_path=output, compiler_factory=lambda: Mock(compile=compile_audio))
        expected = get_cache_key(prepared.original, None, None, None, None, None,
                                 tts_model='test-model', voice_sample_hash=hash_sample_file(sample),
                                 processed_voice_bytes=b'processed reference')
        assert result.cache_dir.name == expected
    asyncio.run(run())
    client.clone_voice.assert_awaited_once()
    client.set_voice_id.assert_not_called()
    assert sample.read_bytes() == b'original reference'


def test_openai_reference_rejection_does_not_start_paid_work(setup):
    source, output = setup
    client = Mock(model='tts-1', generate_audio=AsyncMock(), clone_voice=AsyncMock())
    compiler = Mock()
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter())
        with pytest.raises(ValueError, match='does not support voice cloning'):
            await run_pipeline(prepared, client=client, engine='openai', voice=VoiceInput(reference=source),
                               output_path=output, compiler_factory=compiler)
    asyncio.run(run())
    client.generate_audio.assert_not_called()
    client.clone_voice.assert_not_called()
    compiler.assert_not_called()


def test_mistral_preset_clears_previous_reference_before_generation(setup):
    source, output = setup
    client = get_tts_client('mistral', 'dummy-key')
    client.voice_sample_path = source
    client.voice_sample_bytes = b'old reference'
    async def generate(text, path):
        assert client.voice_sample_path is None
        assert client.voice_sample_bytes is None
        assert client.voice_id == 'en_paul_neutral'
        path.write_bytes(b'valid fake audio' * 20)
    client.generate_audio = generate
    def compile_audio(paths, destination):
        destination.write_bytes(b'compiled output')
        return {}
    async def run():
        prepared = await prepare_text(source, splitter=TextSplitter())
        await run_pipeline(prepared, client=client, engine='mistral', voice=VoiceInput('en_paul_neutral'),
                           output_path=output, compiler_factory=lambda: Mock(compile=compile_audio))
    asyncio.run(run())
