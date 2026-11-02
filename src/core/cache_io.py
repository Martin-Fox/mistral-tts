"""Cross-process cache locking and atomic file publication on local filesystems."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import errno
import json
import math
import os
from pathlib import Path
import tempfile
import time


def _try_lock(stream):
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@asynccontextmanager
async def cache_lock(directory: Path, timeout_seconds: float | None = None):
    """Wait without blocking the event loop; closing the file releases the OS lock.

    The lock file is intentionally never removed (unlinking permits split locks).
    Kernel ownership, rather than a PID/stale-file heuristic, handles crashed owners.
    """
    timeout = float(os.getenv("CACHE_LOCK_TIMEOUT_SECONDS", "3600")) if timeout_seconds is None else timeout_seconds
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("CACHE_LOCK_TIMEOUT_SECONDS must be a finite positive number")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".cache.lock").open("a+b") as stream:
        if os.name == "nt" and stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock(stream)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for cache lock: {directory}") from None
                await asyncio.sleep(min(0.1, remaining))
        try:
            yield
        finally:
            # Close before leaving this scope, including cancellation/exception paths.
            stream.close()


@contextmanager
def staged_file(destination: Path):
    fd, name = tempfile.mkstemp(prefix=".pending-", suffix=destination.suffix, dir=destination.parent)
    os.close(fd)  # Clients/subprocesses must be able to reopen this file on Windows.
    temporary = Path(name)
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def save_json_atomic(destination: Path, data: dict):
    with staged_file(destination) as temporary:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=4)
        temporary.replace(destination)


def save_text_atomic(destination: Path, text: str):
    with staged_file(destination) as temporary:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(destination)


async def generate_chunk_atomic(client, text: str, destination: Path):
    with staged_file(destination) as temporary:
        await client.generate_audio(text, temporary)
        if not temporary.exists() or temporary.stat().st_size <= 100:
            raise RuntimeError(f"Generated chunk audio missing or invalid: {destination}")
        temporary.replace(destination)


async def run_blocking_until_done(function, *args):
    """Keep the cache lock until a compiler thread stops, even after cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()  # Retrieve any thread error before propagating cancellation.
        raise asyncio.CancelledError
    return task.result()
