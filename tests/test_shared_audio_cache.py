"""Shared cache contracts and concurrent TUI jobs without a terminal or provider."""
import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from src import tui
from src.api.factory import DEFAULT_TTS_MODELS
from src.core.audio_cache import AudioCache, validate_chunks


@pytest.mark.parametrize('raw', ['[]', 'null', 'not-json', '{}', '{"chunks":null,"completed":null}'])
def test_malformed_manifest_does_not_reuse_unproven_audio(tmp_path, raw):
    (tmp_path / 'manifest.json').write_text(raw)
    audio = tmp_path / 'chunk_0000.mp3'
    audio.write_bytes(b'old audio' * 30)
    async def generate(text, path):
        path.write_bytes(b'new audio' * 30)
    client = Mock(generate_audio=AsyncMock(side_effect=generate))
    async def run():
        cache = AudioCache(tmp_path)
        async with cache.session(['new source']):
            await cache.ensure_chunk(0, client)
            assert cache.validated_paths() == [audio]
    asyncio.run(run())
    client.generate_audio.assert_awaited_once()
    assert audio.read_bytes() == b'new audio' * 30
    assert json.loads((tmp_path / 'manifest.json').read_text())['completed'] == ['chunk_0000.mp3']


def test_session_required_and_unmarked_audio_cannot_be_compiled(tmp_path):
    cache = AudioCache(tmp_path)
    with pytest.raises(RuntimeError, match='session'):
        cache.validated_paths()
    async def run():
        async with cache.session(['source']):
            with pytest.raises(RuntimeError, match='separate AudioCache'):
                async with cache.session(['other']):
                    pytest.fail('Nested/concurrent use of one instance is forbidden')
            cache.path(0).write_bytes(b'orphaned audio' * 30)
            with pytest.raises(RuntimeError, match='not marked complete'):
                cache.validated_paths()
    asyncio.run(run())
    with pytest.raises(RuntimeError, match='session'):
        cache.is_completed(0)


@pytest.mark.parametrize('chunks', [[], [''], ['   '], [None]])
def test_empty_or_invalid_segments_fail_before_creating_cache(tmp_path, chunks):
    async def run():
        async with AudioCache(tmp_path / 'new').session(chunks):
            pytest.fail('Invalid segmentation was accepted')
    with pytest.raises(ValueError):
        asyncio.run(run())
    assert not (tmp_path / 'new').exists()


def test_count_and_file_validation():
    with pytest.raises(RuntimeError, match='count mismatch'):
        validate_chunks([], 1)
    with pytest.raises(ValueError, match='0 chunks'):
        validate_chunks([], 0)


def test_cached_symlink_is_replaced_without_modifying_its_target(tmp_path):
    directory = tmp_path / 'cache'
    directory.mkdir()
    external = tmp_path / 'external.mp3'
    external.write_bytes(b'keep original audio' * 30)
    path = directory / 'chunk_0000.mp3'
    path.symlink_to(external)
    (directory / 'manifest.json').write_text(json.dumps({'chunks': ['source'], 'completed': [path.name]}))
    async def generate(text, output):
        output.write_bytes(b'generated audio' * 30)
    async def run():
        cache = AudioCache(directory)
        async with cache.session(['source']):
            assert not cache.is_completed(0)
            await cache.ensure_chunk(0, Mock(generate_audio=generate))
            assert cache.validated_paths() == [path]
    asyncio.run(run())
    assert not path.is_symlink()
    assert external.read_bytes() == b'keep original audio' * 30


@pytest.mark.parametrize('engine', ['mistral', 'openai'])
@pytest.mark.parametrize('difference', ['none', 'text', 'voice'])
def test_two_tui_instances_share_or_isolate_cache_as_required(tmp_path, monkeypatch, engine, difference):
    monkeypatch.chdir(tmp_path)
    generated, compiled = [], {}
    active = 0
    maximum = 0
    async def generate(text, path):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        generated.append((text, path))
        try:
            await asyncio.sleep(0.01)
            path.write_bytes(text.encode() + b'\0' + b'a' * 200)
        finally:
            active -= 1
    def client_factory(*args):
        return Mock(model=DEFAULT_TTS_MODELS[engine], generate_audio=generate)
    def compile_audio(paths, output):
        compiled[output.name] = [(path.parent, path.read_bytes().split(b'\0')[0].decode()) for path in paths]
        return {}
    monkeypatch.setattr(tui, 'get_tts_client', client_factory)
    monkeypatch.setattr(tui, 'AudioCompiler', lambda: Mock(compile=compile_audio))
    apps, sources = [], []
    for index in range(2):
        source = tmp_path / f'book-{index}.txt'
        source.write_text('Other book' if index and difference == 'text' else 'Shared book')
        sources.append(source)
        app = tui.BooksmithTUI()
        app.query_one = Mock()
        app.log_message = Mock()
        apps.append(app)
    # The old flat TUI layout must neither be reused nor deleted automatically.
    legacy = tmp_path / 'storage/cache/chunk_0000.mp3'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'legacy audio' * 30)
    async def run():
        calls = []
        for index, app in enumerate(apps):
            voice = 'alloy' if engine == 'openai' else 'en_paul_neutral'
            if index and difference == 'voice':
                voice = 'echo' if engine == 'openai' else 'en_sarah_expressive'
            calls.append(app.process_book(str(sources[index]), '', voice, str(tmp_path / f'out-{index}.mp3'),
                                          'fake-key', engine=engine, openai_key='fake-key'))
        await asyncio.wait_for(asyncio.gather(*calls), timeout=5)
    asyncio.run(run())
    for index, app in enumerate(apps):
        assert not any(str(call.args[0]).startswith('Error:') for call in app.log_message.call_args_list)
        assert compiled[f'out-{index}.mp3'][0][1] == sources[index].read_text()
    first = compiled['out-0.mp3'][0][0]
    second = compiled['out-1.mp3'][0][0]
    assert first.name.startswith('v2_')
    assert (first == second) == (difference == 'none')
    assert len(generated) == (1 if difference == 'none' else 2)
    assert maximum == (1 if difference == 'none' else 2)
    assert legacy.read_bytes() == b'legacy audio' * 30
