import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src import cli as cli_module, web, tui
from src.core import cache_identity
from src.core.cache_identity import get_cache_key, hash_sample_file


def key(**changes):
    params = dict(text='book text', voice_preset='voice', voice_manual_id=None,
                  voice_bytes=None, source_lang=None, target_lang=None)
    params.update(changes)
    return get_cache_key(**params)


@pytest.mark.parametrize('change', [
    {'text': 'different book'}, {'engine': 'openai'}, {'tts_model': 'new-tts-model'},
    {'voice_preset': 'different-voice'}, {'voice_bytes': b'sample'},
    {'max_chars': 500}, {'target_lang': 'Polish'},
])
def test_effective_inputs_change_identity(change, monkeypatch):
    monkeypatch.setattr(cache_identity, 'get_translation_model', lambda: 'configured-model')
    assert key(**change) != key()


def test_structured_identity_prevents_concatenation_collision():
    assert key(text='ab', voice_preset='c') != key(text='a', voice_preset='bc')
    assert key().startswith('v2_')
    assert key() == key()


def test_defaults_and_ignored_parameters_do_not_fragment_cache():
    assert key(voice_preset=None) == key(voice_preset='en_paul_neutral')
    assert key(voice_preset=None, engine='openai') == key(voice_preset=' ALLOY ', engine=' OpenAI ')
    assert key(voice_manual_id='ignored') == key()
    assert key(source_lang='ignored', translation_model='ignored') == key()
    assert key(voice_bytes=b'sample') == key(voice_bytes=b'sample', voice_preset='ignored')


def test_translation_uses_effective_model_and_source_default(monkeypatch):
    monkeypatch.setattr(cache_identity, 'get_translation_model', lambda: 'model-a')
    first = key(target_lang='Polish')
    assert first == key(target_lang='Polish', source_lang='English', translation_model='model-a')
    monkeypatch.setattr(cache_identity, 'get_translation_model', lambda: 'model-b')
    assert key(target_lang='Polish') != first
    assert key(target_lang='Polish', translation_model='model-a') == first
    assert key(target_lang='Polish', source_lang='German') != key(target_lang='Polish')


def test_sample_identity_depends_on_bytes_not_file_path(tmp_path):
    first, second = tmp_path / 'first.wav', tmp_path / 'second.wav'
    first.write_bytes(b'sample-one')
    second.write_bytes(b'sample-one')
    first_key = key(voice_sample_hash=hash_sample_file(first))
    assert first_key == key(voice_sample_hash=hash_sample_file(second))
    assert first_key == key(voice_bytes=b'sample-one')
    first.write_bytes(b'sample-two')
    assert key(voice_sample_hash=hash_sample_file(first)) != first_key


def test_splitter_version_invalidates_cache(monkeypatch):
    original = key()
    monkeypatch.setattr(cache_identity, 'SPLITTER_VERSION', cache_identity.SPLITTER_VERSION + 1)
    assert key() != original


@pytest.fixture
def pipelines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text_path = tmp_path / 'book.txt'
    text_path.write_text('book text')
    translated = tmp_path / 'translated.txt'
    translated.write_text('translated text')
    compiler = Mock()
    compiler.compile.return_value = {}
    generated = []
    client = Mock()
    client.model = 'test-model'
    client.clone_voice = AsyncMock()

    async def generate(text, path):
        generated.append(text)
        path.write_bytes(b'fake-audio' * 100)

    client.generate_audio = AsyncMock(side_effect=generate)
    translation_factory = Mock(side_effect=lambda **kwargs: Mock(
        translate_file=AsyncMock(return_value=translated)))
    for module in (web, cli_module, tui):
        monkeypatch.setattr(module, 'get_tts_client', Mock(return_value=client))
        monkeypatch.setattr(module, 'AudioCompiler', Mock(return_value=compiler))
        monkeypatch.setattr(module, 'MistralTTSClient', translation_factory)
        monkeypatch.setattr(module, 'get_translation_model', lambda: 'configured-model')
    monkeypatch.setattr(web, 'db', Mock())

    def run(interface, engine='mistral', voice='voice', sample=None, target=None):
        compilations_before = compiler.compile.call_count
        if interface == 'cli':
            runner = cli_module.BooksmithCLI('fake-key')
            asyncio.run(runner.run(text_path, sample or Path(voice), tmp_path / 'book.mp3',
                                   target_lang=target, engine=engine, openai_key='fake-key'))
        elif interface == 'tui':
            app = tui.BooksmithTUI()
            app.query_one = Mock()
            app.log_message = Mock()
            asyncio.run(app.process_book(str(text_path), str(sample) if sample else '', voice,
                                         str(tmp_path / 'book.mp3'), 'fake-key', target_lang=target or '',
                                         engine=engine, openai_key='fake-key'))
            assert not any(str(call.args[0]).startswith('Error:') for call in app.log_message.call_args_list)
        else:
            asyncio.run(web.run_generation_pipeline(
                'test-task', 'fake-key', 'book text', None,
                (sample.name, sample.read_bytes()) if sample else None,
                voice, None, None, target, 'book.mp3', engine=engine, openai_key='fake-key',
            ))
        assert compiler.compile.call_count == compilations_before + 1
        return compiler.compile.call_args.args[0][0].parent.resolve()

    return run, generated, client, translation_factory


def test_interfaces_share_identity_for_presets_and_samples(pipelines, tmp_path):
    run, generated, _, _ = pipelines
    first = run('cli')
    assert run('web') == first
    assert run('tui') == first
    assert len(generated) == 1
    sample = tmp_path / 'voice.wav'
    sample.write_bytes(b'same-reference-audio')
    cloned = run('cli', sample=sample)
    assert run('web', sample=sample) == cloned
    assert run('tui', sample=sample) == cloned
    assert len(generated) == 2


@pytest.mark.parametrize('interface', ['cli', 'web', 'tui'])
def test_engine_model_and_changed_sample_regenerate_audio(pipelines, tmp_path, interface):
    run, generated, client, _ = pipelines
    first = run(interface)
    assert run(interface, engine='openai') != first
    client.model = 'new-test-model'
    assert run(interface) != first
    sample = tmp_path / 'voice.wav'
    sample.write_bytes(b'sample-one')
    cloned = run(interface, sample=sample)
    sample.write_bytes(b'sample-two')
    assert run(interface, sample=sample) != cloned
    assert len(generated) == 5


def test_interfaces_use_same_resolved_translation_model(pipelines):
    run, generated, _, translations = pipelines
    first = run('cli', target='Polish')
    assert run('web', target='Polish') == first
    assert run('tui', target='Polish') == first
    assert len(generated) == 1
    assert all(call.kwargs['translation_model'] == 'configured-model' for call in translations.call_args_list)


@pytest.mark.parametrize('interface', ['cli', 'web', 'tui'])
def test_legacy_cache_is_not_reused_or_removed(pipelines, tmp_path, interface):
    run, generated, _, _ = pipelines
    legacy_hash = hashlib.sha256(b'book textvoice').hexdigest()
    legacy = tmp_path / 'storage/cache' / legacy_hash
    legacy.mkdir(parents=True)
    old_manifest = '{"chunks":["book text"],"completed":["chunk_0000.mp3"]}'
    (legacy / 'manifest.json').write_text(old_manifest)
    (legacy / 'chunk_0000.mp3').write_bytes(b'old-audio' * 100)
    current = run(interface)
    assert current != legacy
    assert current.name.startswith('v2_')
    assert generated == ['book text']
    assert (legacy / 'manifest.json').read_text() == old_manifest
    assert (legacy / 'chunk_0000.mp3').read_bytes() == b'old-audio' * 100


@pytest.mark.parametrize('interface', ['cli', 'web', 'tui'])
def test_configured_translation_model_change_regenerates_audio(pipelines, monkeypatch, interface):
    run, generated, _, translations = pipelines
    first = run(interface, target='Polish')
    module = {'cli': cli_module, 'web': web, 'tui': tui}[interface]
    monkeypatch.setattr(module, 'get_translation_model', lambda: 'new-configured-model')
    assert run(interface, target='Polish') != first
    assert generated == ['translated text', 'translated text']
    assert translations.call_args.kwargs['translation_model'] == 'new-configured-model'
