import sys
from unittest.mock import patch

from src.core.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, resolve_binary
from src.web import get_static_dir
from src.desktop import find_available_port, open_browser


def test_resolve_binary_fallback(monkeypatch, tmp_path):
    """When binary is nowhere to be found, it should fall back to the binary name string."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    with patch("shutil.which", return_value=None):
        assert resolve_binary("nonexistent_tool_xyz") == "nonexistent_tool_xyz"


def test_resolve_binary_from_system_path(monkeypatch, tmp_path):
    """When binary is in system PATH, resolve_binary returns standard command name."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        assert resolve_binary("ffmpeg") == "ffmpeg"


def test_resolve_binary_from_meipass(monkeypatch, tmp_path):
    """When running inside a PyInstaller bundle (_MEIPASS), binaries inside _MEIPASS/bin take precedence."""
    meipass_dir = tmp_path / "meipass"
    bin_dir = meipass_dir / "bin"
    bin_dir.mkdir(parents=True)
    fake_ffmpeg = bin_dir / "ffmpeg"
    fake_ffmpeg.touch()

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    resolved = resolve_binary("ffmpeg")
    assert resolved == str(fake_ffmpeg.resolve())


def test_resolve_binary_from_meipass_exe(monkeypatch, tmp_path):
    """When running on Windows inside _MEIPASS, ffmpeg.exe is resolved."""
    meipass_dir = tmp_path / "meipass_win"
    bin_dir = meipass_dir / "bin"
    bin_dir.mkdir(parents=True)
    fake_ffmpeg = bin_dir / "ffmpeg.exe"
    fake_ffmpeg.touch()

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    resolved = resolve_binary("ffmpeg")
    assert resolved == str(fake_ffmpeg.resolve())


def test_resolve_binary_next_to_frozen_executable(monkeypatch, tmp_path):
    """When bundled in onedir frozen mode, binaries in exe_dir/bin take precedence."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe_dir = tmp_path / "app"
    bin_dir = exe_dir / "bin"
    bin_dir.mkdir(parents=True)
    fake_ffprobe = bin_dir / "ffprobe"
    fake_ffprobe.touch()

    monkeypatch.setattr(sys, "executable", str(exe_dir / "mistral-tts"))
    resolved = resolve_binary("ffprobe")
    assert resolved == str(fake_ffprobe.resolve())


def test_get_ffmpeg_and_ffprobe_helpers():
    """Verify get_ffmpeg_path and get_ffprobe_path invoke resolve_binary."""
    with patch("src.core.ffmpeg_utils.resolve_binary") as mock_resolve:
        mock_resolve.side_effect = lambda name: f"/mock/{name}"
        assert get_ffmpeg_path() == "/mock/ffmpeg"
        assert get_ffprobe_path() == "/mock/ffprobe"
        assert mock_resolve.call_count == 2


def test_web_get_static_dir_meipass(monkeypatch, tmp_path):
    """Verify get_static_dir in web.py respects PyInstaller _MEIPASS."""
    meipass_dir = tmp_path / "bundle"
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    expected = meipass_dir / "src" / "web" / "static"
    assert get_static_dir() == expected


def test_web_get_static_dir_dev(monkeypatch):
    """Verify get_static_dir returns existing local static directory in dev mode."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    static_dir = get_static_dir()
    assert static_dir.exists()
    assert (static_dir / "index.html").exists()


def test_desktop_find_available_port():
    """Verify find_available_port returns an available integer port."""
    port = find_available_port(8000)
    assert isinstance(port, int)
    assert 8000 <= port < 8020


def test_desktop_open_browser():
    """Verify open_browser starts a background thread that calls webbrowser.open."""
    with patch("webbrowser.open") as mock_open:
        open_browser("http://127.0.0.1:8000", delay=0.01)
        import time
        time.sleep(0.05)
        mock_open.assert_called_once_with("http://127.0.0.1:8000")


def test_resolve_binary_from_meipass_root(monkeypatch, tmp_path):
    """When binary is placed directly in _MEIPASS root without bin/ or tools/ subfolders."""
    meipass_dir = tmp_path / "meipass_root"
    meipass_dir.mkdir(parents=True)
    fake_ffmpeg = meipass_dir / "ffmpeg"
    fake_ffmpeg.touch()

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    resolved = resolve_binary("ffmpeg")
    assert resolved == str(fake_ffmpeg.resolve())


def test_resolve_binary_windows_platform_precedence(monkeypatch, tmp_path):
    """On Windows (sys.platform.startswith('win')), .exe extension is checked first."""
    exe_dir = tmp_path / "win_app"
    bin_dir = exe_dir / "bin"
    bin_dir.mkdir(parents=True)
    fake_exe = bin_dir / "ffmpeg.exe"
    fake_exe.touch()

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "app.exe"))
    monkeypatch.setattr(sys, "platform", "win32")

    resolved = resolve_binary("ffmpeg")
    assert resolved == str(fake_exe.resolve())


def test_resolve_binary_directory_collision_ignored(monkeypatch, tmp_path):
    """If a candidate matching the binary name is a directory, it must be ignored."""
    meipass_dir = tmp_path / "meipass_dir"
    bin_dir = meipass_dir / "bin"
    bin_dir.mkdir(parents=True)
    # create ffmpeg as a directory
    fake_dir = bin_dir / "ffmpeg"
    fake_dir.mkdir()

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    with patch("shutil.which", return_value=None):
        resolved = resolve_binary("ffmpeg")
        # Should NOT return the directory, should fallback to binary name string
        assert resolved == "ffmpeg"


def test_audio_compiler_invokes_resolved_binaries(tmp_path):
    """Ensure AudioCompiler invokes get_ffmpeg_path and get_ffprobe_path."""
    from src.core.audio_compiler import AudioCompiler
    compiler = AudioCompiler()
    dummy_file = tmp_path / "sample.mp3"
    dummy_file.write_bytes(b"dummy")

    with patch("src.core.audio_compiler.get_ffmpeg_path", return_value="/custom/bin/ffmpeg") as mock_ffmpeg, \
         patch("src.core.audio_compiler.get_ffprobe_path", return_value="/custom/bin/ffprobe") as mock_ffprobe, \
         patch("subprocess.run") as mock_sub:

        # Test duration probing uses custom ffmpeg
        mock_sub.return_value.stderr = "time=00:00:01.00"
        compiler._probe_duration(dummy_file)
        assert mock_ffmpeg.called
        assert mock_sub.call_args[0][0][0] == "/custom/bin/ffmpeg"

        # Test audio info probing uses custom ffprobe
        mock_sub.return_value.stdout = '{"streams": [{"sample_rate": "44100", "channels": 2}]}'
        sample_rate, channels = compiler._probe_audio_properties(dummy_file)
        assert mock_ffprobe.called
        assert mock_sub.call_args[0][0][0] == "/custom/bin/ffprobe"
        assert sample_rate == 44100
        assert channels == 2


def test_web_get_static_dir_fallback(monkeypatch, tmp_path):
    """When _MEIPASS is unset and local directory does not exist, falls back to src/web/static."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    # Patch __file__ in web module to point to an empty directory without web/static
    fake_web_file = tmp_path / "dummy_web.py"
    fake_web_file.touch()
    with patch("src.web.__file__", str(fake_web_file)):
        static_dir = get_static_dir()
        from pathlib import Path
        assert static_dir == Path("src/web/static")



def test_importing_desktop_helpers_does_not_change_working_directory(tmp_path):
    """Desktop helpers must preserve the collection/subprocess storage sandbox."""
    import os
    import subprocess

    result = subprocess.run([
        sys.executable, '-c',
        'from pathlib import Path; import sys; original = Path.cwd(); '
        'import src.desktop; assert Path.cwd() == original; '
        'assert "src.web" not in sys.modules; assert not Path("storage").exists()',
    ], cwd=tmp_path, env=dict(os.environ), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_mistral_preprocessing_and_probe_use_resolved_binaries(tmp_path, monkeypatch):
    """Bundled binaries still pass through the bounded asynchronous runner."""
    import asyncio
    from unittest.mock import AsyncMock, Mock
    from src.api.mistral_client import MistralTTSClient

    reference = tmp_path / 'voice.wav'
    reference.write_bytes(b'synthetic reference')
    async def process(command, *, timeout):
        from pathlib import Path
        assert timeout > 0
        if command[0] == '/bundled/ffmpeg':
            Path(command[-1]).write_bytes(b'processed reference')
            return Mock(stdout=b'', stderr=b'')
        assert command[0] == '/bundled/ffprobe'
        return Mock(stdout=b'1.5\n', stderr=b'')

    runner = AsyncMock(side_effect=process)
    monkeypatch.setattr('src.api.mistral_client.get_ffmpeg_path', lambda: '/bundled/ffmpeg')
    monkeypatch.setattr('src.api.mistral_client.get_ffprobe_path', lambda: '/bundled/ffprobe')
    monkeypatch.setattr('src.api.mistral_client.run_process_async', runner)
    client = MistralTTSClient('synthetic-key')
    client.client = Mock(audio=Mock(speech=Mock(complete_async=AsyncMock(
        return_value=Mock(audio_data=None, audio=b'a' * 200)))))
    async def run():
        await client.clone_voice(reference)
        assert client.voice_sample_bytes == b'processed reference'
        await client.generate_audio('source text', tmp_path / 'chunk.mp3', retry_count=1)
    asyncio.run(run())
    assert reference.read_bytes() == b'synthetic reference'
    assert [call.args[0][0] for call in runner.call_args_list] == ['/bundled/ffmpeg', '/bundled/ffprobe']

def test_web_serves_bundled_assets_outside_source_directory(tmp_path):
    """A fresh WebUI import binds both routes to PyInstaller's asset directory."""
    import os
    import shutil
    import subprocess
    from src import web

    bundle = tmp_path / "Reader's książki bundle"
    assets = bundle / 'src/web/static'
    shutil.copytree(web.STATIC_DIRECTORY, assets)
    original = {path.name: path.read_bytes() for path in assets.iterdir() if path.is_file()}
    working = tmp_path / 'working'
    working.mkdir()
    command = '''
import asyncio
from pathlib import Path
import sys
import httpx
sys._MEIPASS = sys.argv[1]
from src import web
assert web.STATIC_DIRECTORY == Path(sys.argv[1]) / 'src/web/static'
async def run():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='http://test') as client:
        for url, name in (('/', 'index.html'), ('/static/app.js', 'app.js')):
            result = await client.get(url)
            assert result.status_code == 200
            assert result.content == (web.STATIC_DIRECTORY / name).read_bytes()
asyncio.run(run())
assert not Path('src').exists()
'''
    result = subprocess.run([sys.executable, '-c', command, str(bundle)], cwd=working,
                            env=dict(os.environ), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path.name: path.read_bytes() for path in assets.iterdir() if path.is_file()} == original
