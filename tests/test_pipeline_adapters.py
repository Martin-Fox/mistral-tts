"""Compare the completed outputs of CLI/WebUI/TUI using local provider/compiler fakes."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src import cli, tui, web
from src.api.factory import DEFAULT_TTS_MODELS
from src.core.text_splitter import TextSplitter


@pytest.mark.parametrize('engine', ['mistral', 'openai'])
@pytest.mark.parametrize('translate', [False, True])
def test_adapters_produce_the_same_ordered_output_and_reuse_audio(tmp_path, monkeypatch, engine, translate):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'auto')
    source = tmp_path / 'source.txt'
    source.write_text('First sentence. Second sentence. Final words', encoding='utf-8')
    translated = tmp_path / 'translated.txt'
    translated.write_text('Pierwsze zdanie. Drugie zdanie. Koniec bez kropki', encoding='utf-8')
    target = 'Polish' if translate else None
    voice = 'alloy' if engine == 'openai' else 'en_paul_neutral'
    generated, clients = [], []
    async def generate(text, output):
        generated.append(text)
        output.write_bytes(text.encode() + b'\0' + b'a' * 200)
    def create_client(*args):
        client = Mock(model=DEFAULT_TTS_MODELS[engine], generate_audio=generate)
        clients.append(client)
        return client
    def compile_audio(paths, output):
        segments = [path.read_bytes().split(b'\0')[0].decode() for path in paths]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(segments, ensure_ascii=False), encoding='utf-8')
        return {'total_chunks': len(segments)}
    translator = Mock(side_effect=lambda **kwargs: Mock(translate_file=AsyncMock(return_value=translated)))
    for module in (cli, tui, web):
        monkeypatch.setattr(module, 'get_tts_client', create_client)
        monkeypatch.setattr(module, 'AudioCompiler', lambda: Mock(compile=compile_audio))
        monkeypatch.setattr(module, 'TextSplitter', lambda: TextSplitter(20))
        monkeypatch.setattr(module, 'get_translation_model', lambda: 'frozen-model')
        monkeypatch.setattr(module, 'MistralTTSClient', translator)
    database = Mock()
    monkeypatch.setattr(web, 'db', database)
    monkeypatch.setattr(web.global_log_handler, 'database', database)
    outputs = [tmp_path / 'cli.mp3', tmp_path / 'storage/output/contract_web.mp3', tmp_path / 'tui.mp3']
    runner = cli.BooksmithCLI('dummy-key')
    app = tui.BooksmithTUI()
    app.log_message = Mock()
    app.query_one = Mock()
    async def run():
        await runner.run(source, Path(voice), outputs[0], engine=engine, openai_key='dummy-key', target_lang=target)
        await web.run_generation_pipeline('contract', 'dummy-key', source.read_text(), None, None, voice,
                                           None, None, target, 'web.mp3', engine=engine, openai_key='dummy-key')
        await app.process_book(str(source), '', voice, str(outputs[2]), 'dummy-key', engine=engine,
                                openai_key='dummy-key', target_lang=target or '')
    asyncio.run(run())
    expected = TextSplitter(20).split(translated.read_text() if translate else source.read_text())
    assert generated == expected  # Only CLI generates; WebUI and TUI reuse that complete cache.
    assert all(json.loads(output.read_text()) == expected for output in outputs)
    assert any(call.kwargs.get('completed') is True for call in database.update_task.call_args_list)
    assert not any(str(call.args[0]).startswith('Error:') for call in app.log_message.call_args_list)
    for client in clients:
        client.set_voice_id.assert_called_once_with(voice)
    if translate:
        assert translator.call_count == 3
        assert all(call.kwargs['translation_model'] == 'frozen-model' for call in translator.call_args_list)
    else:
        translator.assert_not_called()
