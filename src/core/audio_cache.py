"""Shared manifest, chunk validation and resume contract for CLI, WebUI and TUI."""
from contextlib import asynccontextmanager
import json
from pathlib import Path

from src.core.cache_io import cache_lock, generate_chunk_atomic, save_json_atomic


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(manifest, dict):
            return manifest
    except (OSError, ValueError):
        pass
    return {'chunks': [], 'completed': []}


def valid_chunk(path: Path) -> bool:
    # Codec/decoded-duration verification remains the compiler's responsibility.
    try:
        return not path.is_symlink() and path.is_file() and path.stat().st_size > 100
    except OSError:
        return False


def validate_chunks(paths: list[Path], expected: int):
    if not expected:
        raise ValueError('The split text has 0 chunks.')
    if len(paths) != expected:
        raise RuntimeError(f'Chunk count mismatch: expected {expected}, got {len(paths)} files.')
    for index, path in enumerate(paths):
        if not valid_chunk(path):
            raise RuntimeError(f'Missing or invalid chunk audio file before compilation: {path} (chunk {index + 1}/{expected})')


class AudioCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.manifest_path = self.directory / 'manifest.json'
        self._open = False
        self._manifest = None
        self._chunks = []

    @asynccontextmanager
    async def session(self, chunks):
        """Hold the OS lock from manifest comparison through caller compilation."""
        if self._open:
            raise RuntimeError('Use a separate AudioCache instance for each concurrent job')
        if not chunks or any(not isinstance(chunk, str) or not chunk.strip() for chunk in chunks):
            raise ValueError('The split text must contain non-empty text chunks.')
        self._open = True
        try:
            async with cache_lock(self.directory):
                self._chunks = list(chunks)
                manifest = load_manifest(self.manifest_path)
                previous = manifest.get('chunks', [])
                completed = manifest.get('completed', [])
                previous = previous if isinstance(previous, list) else []
                completed = completed if isinstance(completed, list) else []
                # Compare old text before publishing new text, including on interrupted runs.
                manifest['completed'] = [
                    self.path(index).name for index, chunk in enumerate(self._chunks)
                    if index < len(previous) and previous[index] == chunk
                    and self.path(index).name in completed and valid_chunk(self.path(index))
                ]
                manifest['chunks'] = list(self._chunks)
                save_json_atomic(self.manifest_path, manifest)
                self._manifest = manifest
                yield self
        finally:
            self._manifest = None
            self._open = False

    def path(self, index):
        if not 0 <= index < len(self._chunks):
            raise IndexError(index)
        return self.directory / f'chunk_{index:04d}.mp3'

    def _require_session(self):
        if self._manifest is None:
            raise RuntimeError('Open an AudioCache session before accessing chunks')

    def is_completed(self, index):
        self._require_session()
        path = self.path(index)
        return path.name in self._manifest['completed'] and valid_chunk(path)

    async def ensure_chunk(self, index, client):
        self._require_session()
        path = self.path(index)
        if not self.is_completed(index):
            await generate_chunk_atomic(client, self._chunks[index], path)
            if path.name not in self._manifest['completed']:
                self._manifest['completed'].append(path.name)
            save_json_atomic(self.manifest_path, self._manifest)
        return path

    def validated_paths(self):
        self._require_session()
        paths = [self.path(index) for index in range(len(self._chunks))]
        validate_chunks(paths, len(self._chunks))
        if any(not self.is_completed(index) for index in range(len(self._chunks))):
            raise RuntimeError('Cannot compile chunks not marked complete in the current manifest')
        return paths
