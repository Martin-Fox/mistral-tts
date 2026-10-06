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


