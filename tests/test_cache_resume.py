"""Resume regressions using real manifests/files and fake TTS/compilation."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src import cli as cli_module, web


@pytest.fixture(params=['web', 'cli'])
def pipeline(request, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chunks = ['first', 'second', 'third']
    splitter = Mock()
    splitter.max_chars = 1000
    splitter.split.side_effect = lambda _: list(chunks)
    generated = []

    async def generate(text, path):
        generated.append(text)
        path.write_bytes(text.encode() * 200)

    tts = Mock()
    tts.model = "voxtral-mini-tts-2603"
    tts.generate_audio = AsyncMock(side_effect=generate)
    compiler = Mock()
    compiler.compile.return_value = {}
    module = web if request.param == 'web' else cli_module
    monkeypatch.setattr(module, 'get_tts_client', Mock(return_value=tts))
    monkeypatch.setattr(module, 'AudioCompiler', Mock(return_value=compiler))
    if request.param == 'web':
        monkeypatch.setattr(web, 'db', Mock())
        monkeypatch.setattr(web, 'TextSplitter', Mock(return_value=splitter))

        async def run():
            await web.run_generation_pipeline(
                task_id='test-resume', api_key='fake-key', text_content='stable source',
                text_file_data=None, voice_file_data=None, voice_preset='test-voice',
                voice_manual_id=None, source_lang=None, target_lang=None,
                output_filename='test.mp3',
            )
    else:
        source = tmp_path / 'input.txt'
        source.write_text('stable source')
        client = cli_module.BooksmithCLI('fake-key')
        client.splitter = splitter

        async def run():
            await client.run(source, Path('test-voice'), tmp_path / 'test.mp3')

    def invoke():
        # WebUI records failures in the database; CLI raises them to its caller.
        try:
            asyncio.run(run())
        except RuntimeError as error:
            assert str(error) == 'simulated interruption'

    invoke()
    manifest_path, = list((tmp_path / 'storage/cache').glob('*/manifest.json'))
    generated.clear()
    return invoke, chunks, generated, tts, compiler, manifest_path


def test_identical_segments_reuse_audio(pipeline):
    invoke, _, generated, _, compiler, path = pipeline
    invoke()
    assert generated == []
    assert compiler.compile.call_count == 2
    assert len(json.loads(path.read_text())['completed']) == 3


def test_changed_segment_is_regenerated(pipeline):
    invoke, chunks, generated, _, _, path = pipeline
    chunks[1] = 'replacement'
    invoke()
    assert generated == ['replacement']
    assert json.loads(path.read_text())['chunks'] == chunks
    assert (path.parent / 'chunk_0001.mp3').read_bytes() == b'replacement' * 200


@pytest.mark.parametrize('old_chunks', [[], ['first'], None])
def test_missing_or_partial_text_metadata_cannot_mark_audio_complete(pipeline, old_chunks):
    invoke, _, generated, _, _, path = pipeline
    manifest = json.loads(path.read_text())
    manifest['chunks'] = old_chunks
    path.write_text(json.dumps(manifest))
    invoke()
    assert generated == (['second', 'third'] if old_chunks else ['first', 'second', 'third'])


@pytest.mark.parametrize("fail_at", [0, 1])
def test_interruption_does_not_relabel_stale_audio_as_new(pipeline, fail_at):
    invoke, chunks, generated, tts, compiler, path = pipeline
    chunks[:] = ['new-first', 'new-second', 'new-third']
    generate = tts.generate_audio.side_effect

    async def fail_second(text, output):
        if text == chunks[fail_at]:
            raise RuntimeError('simulated interruption')
        await generate(text, output)

    tts.generate_audio.side_effect = fail_second
    invoke()
    manifest = json.loads(path.read_text())
    assert manifest['chunks'] == chunks
    assert manifest['completed'] == [f'chunk_{i:04d}.mp3' for i in range(fail_at)]
    assert compiler.compile.call_count == 1
    generated.clear()
    tts.generate_audio.side_effect = generate
    invoke()
    assert generated == chunks[fail_at:]
    assert json.loads(path.read_text())['completed'] == [f'chunk_{i:04d}.mp3' for i in range(3)]


@pytest.mark.parametrize('invalid', ['missing', 'small'])
def test_invalid_cached_file_is_regenerated_without_duplicate_markers(pipeline, invalid):
    invoke, _, generated, _, _, path = pipeline
    audio = path.parent / 'chunk_0001.mp3'
    if invalid == 'missing':
        audio.unlink()
    else:
        audio.write_bytes(b'too small')
    invoke()
    assert generated == ['second']
    assert len(json.loads(path.read_text())['completed']) == 3
