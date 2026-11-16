"""Text completeness regressions; all translation responses are local fakes."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest

from src.api.mistral_client import MistralTTSClient
from src.core.epub_parser import HTMLTextExtractor, extract_text_from_epub, read_input_text
from src.core.text_decoding import decode_text
from src.core.text_splitter import TextSplitter
from src.core.resource_limits import ResourceLimitExceeded
from src.core import task_store


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'utf-32'])
def test_unicode_input_preserved(tmp_path, monkeypatch, encoding):
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'auto')
    text = 'Zażółć gęślą jaźń. Końcowe zdanie bez kropki'
    path = tmp_path / 'input.txt'
    path.write_bytes(text.encode(encoding))
    assert read_input_text(path) == text


def test_explicit_legacy_encoding_and_invalid_bytes(monkeypatch):
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'auto')
    text = 'Zażółć gęślą jaźń'
    with pytest.raises(ValueError, match='Cannot decode'):
        decode_text(text.encode('cp1250'))
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'cp1250')
    assert decode_text(text.encode('cp1250')) == text
    assert decode_text(text.encode(), encoding='utf-8') == text
    with pytest.raises(ValueError):
        decode_text(b'valid\xfftail', encoding='utf-8')
    with pytest.raises(ValueError):
        decode_text(b'text', encoding='unknown-encoding')
    with pytest.raises(ValueError, match='NUL'):
        decode_text('hello'.encode('utf-16-le'), encoding='auto')
    assert decode_text(text.encode('utf-16-le'), encoding='utf-16-le') == text


def make_epub(path, *, manifest, spine, chapters):
    with ZipFile(path, 'w') as archive:
        archive.writestr('META-INF/container.xml',
                         '<?xml version="1.0" encoding="UTF-16"?><container><rootfiles>'
                         '<rootfile full-path="OPS/book.opf"/></rootfiles></container>'.encode('utf-16'))
        archive.writestr('OPS/book.opf', f'<package><manifest>{manifest}</manifest><spine>{spine}</spine></package>')
        for name, data in chapters.items():
            archive.writestr('OPS/' + name, data)


@pytest.mark.parametrize('missing', ['manifest', 'chapter', 'idref'])
def test_epub_never_silently_skips_missing_spine_content(tmp_path, missing):
    path = tmp_path / 'book.epub'
    manifest = '<item id="one" href="one.xhtml"/>'
    if missing != 'manifest':
        manifest += '<item id="two" href="two.xhtml"/>'
    spine = '<itemref idref="one"/>' + ('<itemref/>' if missing == 'idref' else '<itemref idref="two"/>')
    make_epub(path, manifest=manifest, spine=spine, chapters={'one.xhtml': '<p>First chapter</p>'})
    with pytest.raises(ValueError, match='missing'):
        extract_text_from_epub(path)


def test_epub_declared_charset_and_url_fragment(tmp_path):
    path = tmp_path / 'book.epub'
    text = 'Zażółć gęślą jaźń'
    make_epub(path, manifest='<item id="one" href="chapter%20one.xhtml#start"/>',
              spine='<itemref idref="one"/>', chapters={
                  'chapter one.xhtml': ('<html><head><meta charset="windows-1250"></head>'
                                        '<body><p>' + text + '</p></body></html>').encode('cp1250')})
    assert extract_text_from_epub(path) == text


def test_html_ignored_ancestors_and_void_elements():
    parser = HTMLTextExtractor()
    parser.feed('<head><title>Hidden</title><div>Also hidden</div><meta charset="utf-8"></head>'
                '<body><p>First<br/>Second<img src="x">End</p></body>')
    assert parser.get_text() == 'First\n\nSecondEnd'


@pytest.mark.parametrize('maximum', [1, 10, 2500])
def test_exact_boundary_has_no_empty_chunk(maximum):
    assert TextSplitter(maximum).split('x' * maximum) == ['x' * maximum]


def test_job_encoding_is_frozen_but_inline_text_is_utf8(tmp_path, monkeypatch):
    monkeypatch.setattr(task_store, 'TASK_ROOT', tmp_path)
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'cp1250')
    task_store.save_job('upload', {'text_file_data': ('input.txt', 'żółć'.encode('cp1250'))})
    task_store.save_job('inline', {'text_content': 'żółć'})
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'utf-16')
    assert task_store.load_job('upload')['input_encoding'] == 'cp1250'
    inline = task_store.load_job('inline')
    assert inline['input_encoding'] == 'utf-8'
    assert decode_text(inline['text_file_data'][1], inline['input_encoding']) == 'żółć'
    spec_path = task_store.task_directory('upload') / 'spec.json'
    spec = json.loads(spec_path.read_text())
    spec['splitter_version'] = 1
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match='incompatible'):
        task_store.load_job('upload')


def response(content, reason='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=reason)])


@pytest.fixture
def translator(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('INPUT_TEXT_ENCODING', 'auto')
    client = MistralTTSClient('dummy-key')
    client.client = Mock()
    client.client.chat.complete_async = AsyncMock()
    monkeypatch.setattr('src.api.mistral_client.asyncio.sleep', AsyncMock())
    return client


@pytest.mark.anyio
@pytest.mark.parametrize('content', [None, '', '  ', [], ['text']])
async def test_invalid_translation_is_rejected(translator, content):
    translator.client.chat.complete_async.return_value = response(content)
    with pytest.raises(ValueError):
        await translator.translate_text('Source', 'en', 'pl')
    assert translator.client.chat.complete_async.await_count == 1


@pytest.mark.anyio
async def test_long_token_translation_is_bounded_and_complete(translator, tmp_path):
    source = 'a' * 6000 + 'Z'
    path = tmp_path / 'book.txt'
    path.write_text(source)
    seen = []
    async def complete(**kwargs):
        text = kwargs['messages'][0]['content'].split('Text to translate:\n', 1)[1]
        seen.append(text)
        assert 0 < len(text) <= 2500
        return response(text)
    translator.client.chat.complete_async.side_effect = complete
    output = await translator.translate_file(path, 'en', 'pl')
    assert ''.join(seen) == source
    assert output.read_text().replace(' ', '').replace('\n', '') == source


@pytest.mark.anyio
async def test_truncation_splits_source_instead_of_accepting_partial_output(translator):
    source = 'a' * 999 + 'Z'
    seen = []
    async def complete(**kwargs):
        text = kwargs['messages'][0]['content'].split('Text to translate:\n', 1)[1]
        seen.append(text)
        return response('PARTIAL', 'length') if len(text) > 300 else response(text)
    translator.client.chat.complete_async.side_effect = complete
    result = await translator.translate_text(source, 'en', 'pl')
    assert result.replace(' ', '') == source
    assert 'PARTIAL' not in result
    assert len(seen) == 7


@pytest.mark.anyio
async def test_persistent_truncation_stops_and_preserves_existing_output(translator, tmp_path):
    path = tmp_path / 'source.txt'
    path.write_text('x' * 2500)
    destination = tmp_path / 'storage/translations/previous.txt'
    destination.parent.mkdir(parents=True)
    destination.write_text('complete previous output')
    translator.client.chat.complete_async.return_value = response('partial', 'length')
    with pytest.raises(RuntimeError, match='capacity'):
        await translator.translate_file(path, 'en', 'pl', output_filename='previous.txt')
    assert translator.client.chat.complete_async.await_count == 5
    assert destination.read_text() == 'complete previous output'


@pytest.mark.anyio
@pytest.mark.parametrize('bad', [{'translations': 'ab'}, {'translations': ['', 'x']},
                               {'translations': [None, 'x']}, ['a', 'b'], 'not-json'])
async def test_invalid_srt_batch_uses_validated_individual_fallback(translator, tmp_path, bad):
    path = tmp_path / 'input.srt'
    path.write_text('1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n'
                    '2\n00:00:03,000 --> 00:00:04,000\nLast')
    translator.client.chat.complete_async.side_effect = [response(json.dumps(bad)), response('Pierwszy'), response('Ostatni')]
    output = await translator.translate_file(path, 'en', 'pl')
    assert output.read_text() == ('1\n00:00:01,000 --> 00:00:02,000\nPierwszy\n\n'
                                  '2\n00:00:03,000 --> 00:00:04,000\nOstatni')
    assert translator.client.chat.complete_async.await_count == 3


@pytest.mark.anyio
async def test_long_srt_cue_and_batches_obey_payload_budget(translator, tmp_path):
    path = tmp_path / 'input.srt'
    texts = ['a' * 6000 + 'Z'] + [str(i) + 'word ' * 80 for i in range(25)]
    path.write_text('\n\n'.join(f'{i + 1}\n00:00:01,000 --> 00:00:02,000\n{text}' for i, text in enumerate(texts)))
    seen = []
    async def complete(**kwargs):
        prompt = kwargs['messages'][0]['content']
        if 'response_format' in kwargs:
            payload = prompt.split('Input JSON:\n', 1)[1]
            assert len(payload) <= 2500
            segments = json.loads(payload)['texts']
            assert len(segments) <= 25
            seen.extend(segments)
            return response(json.dumps({'translations': segments}))
        text = prompt.split('Text to translate:\n', 1)[1]
        assert len(text) <= 2500
        seen.append(text)
        return response(text)
    translator.client.chat.complete_async.side_effect = complete
    output = await translator.translate_file(path, 'en', 'pl')
    assert ''.join(''.join(seen).split()) == ''.join(''.join(texts).split())
    assert output.read_text().count('00:00:01,000 --> 00:00:02,000') == 26
    assert 'Z' in output.read_text()


@pytest.mark.anyio
@pytest.mark.parametrize('suffix', ['.txt', '.srt'])
async def test_total_output_budget_stops_without_publishing_or_fallback(translator, tmp_path, monkeypatch, suffix):
    path = tmp_path / ('input' + suffix)
    if suffix == '.txt':
        monkeypatch.setenv('MAX_TEXT_CHARS', '5000')
        path.write_text('a' * 2501)
        translator.client.chat.complete_async.return_value = response('x' * 3000)
    else:
        monkeypatch.setenv('MAX_TEXT_CHARS', '4000')
        path.write_text('1\n00:00:01,000 --> 00:00:02,000\n' + 'a' * 1500 +
                        '\n\n2\n00:00:03,000 --> 00:00:04,000\n' + 'b' * 1500)
        translator.client.chat.complete_async.return_value = response(json.dumps({'translations': ['x' * 2200]}))
    with pytest.raises(ResourceLimitExceeded):
        await translator.translate_file(path, 'en', 'pl', output_filename='final' + suffix)
    assert translator.client.chat.complete_async.await_count == 2
    assert not (tmp_path / ('storage/translations/final' + suffix)).exists()
