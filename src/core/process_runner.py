"""Finite process budgets and cancellation-safe async child cleanup."""
import asyncio
import math
import os
import subprocess
import time
from contextvars import ContextVar

process_cancellation = ContextVar('process_cancellation', default=None)


def setting(name, default):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a finite positive number") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def process_budget(duration=0, *, probe=False):
    base = setting('AUDIO_PROBE_TIMEOUT_SECONDS', 30) if probe else setting('AUDIO_PROCESS_TIMEOUT_SECONDS', 120)
    factor = setting('AUDIO_TIMEOUT_FACTOR', 0.1)
    ceiling = setting('AUDIO_MAX_TIMEOUT_SECONDS', 7200)
    duration = duration if math.isfinite(duration) and duration > 0 else 0
    return min(ceiling, base + duration * factor)


def run_process(cmd, *, timeout, text=False):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Process timeout must be finite and positive')
    cancellation = process_cancellation.get()
    if cancellation is not None:
        if cancellation.is_set():
            raise RuntimeError('Audio processing cancelled')
        with subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=text) as process:
            deadline = time.monotonic() + timeout
            while True:
                if cancellation.is_set():
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise RuntimeError('Audio processing cancelled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    # subprocess.run kills and waits for its direct child on timeout.
    return subprocess.run(cmd, capture_output=True, check=True, text=text,
                          stdin=subprocess.DEVNULL, timeout=timeout)


async def _stop(process, communication):
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(asyncio.shield(communication), 2)
        except asyncio.TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
    await communication


async def run_process_async(cmd, *, timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Process timeout must be finite and positive')
    process = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    communication = asyncio.create_task(process.communicate())
    try:
        stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as error:
        cleanup = asyncio.create_task(_stop(process, communication))
        # Repeated cancellation must not orphan the child or close staging early.
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()
        if isinstance(error, asyncio.TimeoutError):
            failure = TimeoutError(f"{cmd[0]} exceeded its {timeout:g}s process budget")
            failure.stderr = communication.result()[1]
            raise failure from None
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
