"""Portable release checks; run on native Windows as well as Linux."""
import asyncio
from pathlib import Path
import socket
import subprocess
import sys
import threading

import httpx
import pytest

from src import web
from src.core.process_runner import process_cancellation, run_process


def test_web_assets_are_read_from_source_when_working_directory_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url='http://test') as client:
            for url, filename in (('/', 'index.html'), ('/static/app.js', 'app.js'),
                                  ('/static/styles.css', 'styles.css')):
                response = await client.get(url)
                assert response.status_code == 200
                assert response.content == (web.STATIC_DIRECTORY / filename).read_bytes()
    asyncio.run(run())
    assert web.STATIC_DIRECTORY == Path(web.__file__).resolve().parent / 'web/static'
    assert not (tmp_path / 'src').exists()


@pytest.mark.parametrize('threaded', [False, True])
def test_process_diagnostics_do_not_depend_on_ansi_locale(threaded):
    # Includes valid UTF-8 and malformed bytes: neither may break ASCII time parsing.
    command = [sys.executable, '-c',
               'import sys;sys.stderr.buffer.write("żółw".encode("utf-8") + b"\\x81 time=00:00:01.00")']
    token = process_cancellation.set(threading.Event() if threaded else None)
    try:
        result = run_process(command, timeout=5, text=True)
        assert result.stderr == 'żółw\ufffd time=00:00:01.00'
        binary = run_process(command, timeout=5)
        assert binary.stderr == 'żółw'.encode() + b'\x81 time=00:00:01.00'
    finally:
        process_cancellation.reset(token)


def test_network_guard_allows_loopback_ipc_but_blocks_external_ipv6():
    # Windows socketpair/asyncio use loopback TCP rather than Unix sockets.
    with socket.socket() as listener:
        listener.settimeout(2)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        with socket.socket() as connection:
            connection.settimeout(2)
            connection.connect(listener.getsockname())
            peer, _ = listener.accept()
            with peer:
                peer.settimeout(2)
                connection.sendall(b'local IPC')
                assert peer.recv(9) == b'local IPC'
    with socket.socket(socket.AF_INET6) as connection:
        with pytest.raises(AssertionError, match='disabled'):
            connection.connect(('2001:db8::1', 443))


def test_ffmpeg_and_ffprobe_available():
    for executable in ('ffmpeg', 'ffprobe'):
        result = subprocess.run([executable, '-version'], capture_output=True, timeout=10, check=True)
        assert b'version' in result.stdout
