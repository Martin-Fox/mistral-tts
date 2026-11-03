"""Framework-independent text preparation and audiobook generation service."""
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from src.api.base_client import BaseTTSClient
from src.api.factory import DEFAULT_TTS_MODELS
from src.core.audio_cache import AudioCache
from src.core.audio_compiler import AudioCompiler
from src.core.cache_identity import get_cache_key, hash_sample_file
from src.core.cache_io import run_blocking_until_done
from src.core.epub_parser import read_input_text
from src.core.config import get_translation_model
from src.core.text_splitter import TextSplitter


@dataclass(frozen=True)
class PipelineProgress:
    stage: str
    current: int = 0
    total: int = 0
    cached: bool = False
    characters: int = 0


ProgressCallback = Callable[[PipelineProgress], None]
TranslationAdapter = Callable[[Path, str, str, str | None], Awaitable[Path]]


@dataclass(frozen=True)
class PreparedText:
    original: str
    chunks: list[str]
    source_lang: str | None
    target_lang: str | None
    translation_model: str | None
    max_chars: int


@dataclass(frozen=True)
class VoiceInput:
    voice_id: str | None = None
    reference: Path | None = None


@dataclass(frozen=True)
class PipelineResult:
    output_path: Path
    cache_dir: Path
    chunk_count: int
    compilation: dict


def _report(callback, stage, **values):
    if callback is not None:
        callback(PipelineProgress(stage, **values))


async def prepare_text(
    path: Path, *, splitter: TextSplitter, source_lang=None, target_lang=None,
    translation_model=None, input_encoding=None,
    translate: TranslationAdapter | None = None, progress: ProgressCallback | None = None,
) -> PreparedText:
    """Adapters own uploads/checkpoints; translated files are always read as UTF-8."""
    _report(progress, 'Reading Text')
    original = read_input_text(path, encoding=input_encoding)
    translation_model = (translation_model or get_translation_model()) if target_lang else None
    text = original
    if target_lang:
        if translate is None:
            raise ValueError('A translation adapter is required for target_lang')
        _report(progress, 'Translating')
        translated = await translate(path, source_lang or 'English', target_lang, translation_model)
        text = read_input_text(translated, encoding='utf-8')
    _report(progress, 'Splitting Text')
    chunks = splitter.split(text)
    if not chunks:
        raise ValueError('The split text has 0 chunks.')
    _report(progress, 'Text Ready', total=len(chunks), characters=sum(len(chunk) for chunk in chunks))
    return PreparedText(original, chunks, source_lang, target_lang, translation_model, splitter.max_chars)


async def run_pipeline(
    prepared: PreparedText, *, client: BaseTTSClient, engine: str, voice: VoiceInput,
    output_path: Path, compiler_factory: Callable[[], AudioCompiler],
    cache_root: Path = Path('storage/cache'), progress: ProgressCallback | None = None,
    cache_ready: Callable[[Path], None] | None = None,
) -> PipelineResult:
    """Propagate failures/cancellation; keep the cache locked through verified compilation.

    Progress callbacks run synchronously on the caller's event loop. A callback
    failure stops the pipeline, just like a persistence/UI error in the adapters.
    """
    engine = engine.strip().lower()
    if engine not in DEFAULT_TTS_MODELS:
        raise ValueError(f'Unknown TTS engine: {engine}')
    _report(progress, 'Configuring Voice')
    sample_hash = None
    voice_id = voice.voice_id or ('alloy' if engine == 'openai' else 'en_paul_neutral')
    if voice.reference is not None:
        if engine == 'openai':
            raise ValueError('OpenAI TTS does not support voice cloning. Please select an OpenAI preset voice instead.')
        if not voice.reference.exists():
            raise FileNotFoundError(f'Voice file not found: {voice.reference}')
        sample_hash = hash_sample_file(voice.reference)
        await client.clone_voice(voice.reference)
    else:
        client.set_voice_id(voice_id)
    key = get_cache_key(
        prepared.original, voice_id, None, None, prepared.source_lang, prepared.target_lang,
        prepared.translation_model, engine=engine, tts_model=client.model,
        voice_sample_hash=sample_hash, max_chars=prepared.max_chars,
        processed_voice_bytes=getattr(client, 'voice_sample_bytes', None),
    )
    cache = AudioCache(cache_root / key)
    if cache_ready is not None:
        cache_ready(cache.directory)
    total = len(prepared.chunks)
    _report(progress, 'Waiting for Cache', total=total)
    async with cache.session(prepared.chunks):
        _report(progress, 'Generating Audio', total=total)
        for index in range(total):
            cached = cache.is_completed(index)
            _report(progress, 'Generating Chunk', current=index + 1, total=total, cached=cached)
            await cache.ensure_chunk(index, client)
            _report(progress, 'Chunk Ready', current=index + 1, total=total, cached=cached)
        paths = cache.validated_paths()
        _report(progress, 'Compiling Audiobook', total=total)
        compiler = compiler_factory()
        compilation = await run_blocking_until_done(compiler.compile, paths, output_path)
        return PipelineResult(output_path, cache.directory, total, compilation)
