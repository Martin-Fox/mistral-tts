import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch
from src.core.audio_compiler import AudioCompiler

def _generate_test_audio(path: Path, duration_s: float = 1.0, sample_rate: int = 22050):
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=440:r={sample_rate}",
        "-t", str(duration_s),
        "-q:a", "9",
        str(path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def test_compile_empty_chunks_raises_value_error(tmp_path):
    compiler = AudioCompiler()
    with pytest.raises(ValueError, match="No audio chunks provided"):
        compiler.compile([], tmp_path / "out.mp3")

def test_compile_missing_chunk_raises_file_not_found(tmp_path):
    compiler = AudioCompiler()
    with pytest.raises(FileNotFoundError, match="Chunk file not found"):
        compiler.compile([tmp_path / "nonexistent.mp3"], tmp_path / "out.mp3")

def test_compile_empty_chunk_raises_runtime_error(tmp_path):
    empty_file = tmp_path / "empty.mp3"
    empty_file.touch()
    compiler = AudioCompiler()
    with pytest.raises(RuntimeError, match="Chunk file is empty"):
        compiler.compile([empty_file], tmp_path / "out.mp3")

def test_compile_successful_with_trailing_silence(tmp_path):
    c1 = tmp_path / "chunk1.mp3"
    c2 = tmp_path / "chunk2.mp3"
    _generate_test_audio(c1, duration_s=1.0)
    _generate_test_audio(c2, duration_s=1.0)

    output = tmp_path / "output.mp3"
    compiler = AudioCompiler(pause_duration_s=0.5, trailing_silence_s=1.0)
    meta = compiler.compile([c1, c2], output)

    assert output.exists()
    assert output.stat().st_size > 0
    assert meta["total_chunks"] == 2
    # expected: 1.0 + 0.5 + 1.0 + 1.0 = 3.5s
    assert abs(meta["expected_duration"] - 3.5) < 0.2
    assert abs(meta["output_duration"] - 3.5) < 0.5

def test_compile_truncation_detection_raises_runtime_error(tmp_path):
    c1 = tmp_path / "chunk1.mp3"
    c2 = tmp_path / "chunk2.mp3"
    _generate_test_audio(c1, duration_s=2.0)
    _generate_test_audio(c2, duration_s=2.0)

    output = tmp_path / "output.mp3"
    compiler = AudioCompiler(pause_duration_s=0.5, trailing_silence_s=1.0)

    # Simulate output file duration being truncated to 1.0s instead of ~5.5s
    orig_probe = compiler._probe_duration
    def mock_probe(p):
        if p == output:
            return 1.0
        return orig_probe(p)

    with patch.object(compiler, "_probe_duration", side_effect=mock_probe):
        with pytest.raises(RuntimeError, match="Audiobook compilation truncated output"):
            compiler.compile([c1, c2], output)


def test_compile_tolerance_boundary_pass_and_fail(tmp_path):
    c1 = tmp_path / "chunk1.mp3"
    c2 = tmp_path / "chunk2.mp3"
    _generate_test_audio(c1, duration_s=4.0)
    _generate_test_audio(c2, duration_s=4.0)

    output = tmp_path / "output.mp3"
    compiler = AudioCompiler(pause_duration_s=0.5, trailing_silence_s=1.0)
    orig_probe = compiler._probe_duration

    # Calculate actual expected duration based on chunk probing
    actual_chunks_duration = orig_probe(c1) + orig_probe(c2)
    expected_duration = actual_chunks_duration + 0.5 + 1.0
    cutoff_threshold = expected_duration - 4.0  # tolerance = 4.0s

    # 1. Output duration above threshold (threshold + 0.5s) -> should PASS
    def mock_probe_pass(p):
        if p == output:
            return cutoff_threshold + 0.5
        return orig_probe(p)

    with patch.object(compiler, "_probe_duration", side_effect=mock_probe_pass):
        meta = compiler.compile([c1, c2], output)
        assert meta["output_duration"] == cutoff_threshold + 0.5
        assert abs(meta["expected_duration"] - expected_duration) < 0.01

    # 2. Output duration below threshold (threshold - 0.5s) -> should FAIL with RuntimeError
    def mock_probe_fail(p):
        if p == output:
            return cutoff_threshold - 0.5
        return orig_probe(p)

    with patch.object(compiler, "_probe_duration", side_effect=mock_probe_fail):
        with pytest.raises(RuntimeError, match="Audiobook compilation truncated output: expected at least"):
            compiler.compile([c1, c2], output)



def test_compile_single_chunk_without_pauses(tmp_path):
    c1 = tmp_path / "single_chunk.mp3"
    _generate_test_audio(c1, duration_s=1.5)

    output = tmp_path / "single_output.mp3"
    compiler = AudioCompiler(pause_duration_s=0.5, trailing_silence_s=1.0)
    meta = compiler.compile([c1], output)

    assert output.exists()
    assert meta["total_chunks"] == 1
    # expected: 1.5 + 0 * 0.5 + 1.0 = 2.5s
    assert abs(meta["expected_duration"] - 2.5) < 0.2
    assert abs(meta["output_duration"] - 2.5) < 0.5


def test_compile_zero_pauses_and_trailing_silence(tmp_path):
    c1 = tmp_path / "c1.mp3"
    c2 = tmp_path / "c2.mp3"
    _generate_test_audio(c1, duration_s=1.0)
    _generate_test_audio(c2, duration_s=1.0)

    output = tmp_path / "zero_output.mp3"
    compiler = AudioCompiler(pause_duration_s=0.0, trailing_silence_s=0.0)
    meta = compiler.compile([c1, c2], output)

    assert output.exists()
    # expected: 1.0 + 1.0 = 2.0s
    assert abs(meta["expected_duration"] - 2.0) < 0.2


def test_probe_duration_error_handling(tmp_path):
    compiler = AudioCompiler()
    # Non-existent file
    with pytest.raises(FileNotFoundError, match="Audio file not found for duration probing"):
        compiler._probe_duration(tmp_path / "missing.mp3")

    # Invalid / empty probing
    dummy_file = tmp_path / "dummy.mp3"
    dummy_file.write_text("invalid")
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with pytest.raises(RuntimeError, match="Failed to probe duration"):
            compiler._probe_duration(dummy_file)


def test_probe_duration_exact_ffmpeg_null_decoding(tmp_path):
    compiler = AudioCompiler()
    dummy_file = tmp_path / "test.mp3"
    dummy_file.write_text("fake audio")

    fake_stderr = (
        "Output #0, null, to 'pipe:':\n"
        "size=N/A time=00:00:05.12 bitrate=N/A speed=100x\n"
        "size=N/A time=00:01:23.45 bitrate=N/A speed=120x\n"
        "video:0kB audio:100kB\n"
    )

    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = subprocess.CompletedProcess(
            args=["ffmpeg", "-nostats", "-v", "info", "-i", str(dummy_file), "-f", "null", "-"],
            returncode=0,
            stdout="",
            stderr=fake_stderr
        )
        duration = compiler._probe_duration(dummy_file)

        mock_sub.assert_called_once_with(
            ["ffmpeg", "-nostats", "-v", "info", "-i", str(dummy_file), "-f", "null", "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30.0
        )
        # 1 * 60 + 23.45 = 83.45
        assert duration == pytest.approx(83.45, rel=1e-5)


def test_probe_duration_timeout_raises_runtime_error(tmp_path):
    compiler = AudioCompiler()
    dummy_file = tmp_path / "test.mp3"
    dummy_file.write_text("fake audio")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30.0)):
        with pytest.raises(RuntimeError, match="Failed to probe duration"):
            compiler._probe_duration(dummy_file)


@pytest.mark.parametrize("corrupt_stderr", [
    "size=N/A time=N/A bitrate=N/A",
    "size=N/A time=--:--:-- bitrate=N/A",
    "size=N/A time=12:34 bitrate=N/A",  # missing fractional seconds
    "[mp3 @ 0x55555] Header missing\nConversion failed!\n",
    "Output #0, null, to 'pipe:':\nvideo:0kB audio:0kB\n",
    "",
])
def test_probe_duration_corrupt_stderr_raises_runtime_error(tmp_path, corrupt_stderr):
    compiler = AudioCompiler()
    dummy_file = tmp_path / "corrupt.mp3"
    dummy_file.write_text("dummy")

    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout="",
            stderr=corrupt_stderr
        )
        with pytest.raises(RuntimeError, match="Failed to probe duration"):
            compiler._probe_duration(dummy_file)


def test_probe_duration_ffmpeg_process_failure_raises_runtime_error(tmp_path):
    compiler = AudioCompiler()
    dummy_file = tmp_path / "failing.mp3"
    dummy_file.write_text("dummy")

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr="ffmpeg error")):
        with pytest.raises(RuntimeError, match="Failed to probe duration"):
            compiler._probe_duration(dummy_file)


def test_probe_duration_multihour_and_high_precision(tmp_path):
    compiler = AudioCompiler()
    dummy_file = tmp_path / "long.mp3"
    dummy_file.write_text("dummy")

    fake_stderr = (
        "Output #0, null, to 'pipe:':\n"
        "size=N/A time=00:00:10.500 bitrate=N/A speed=10x\n"
        "[warning] frame rate conversion\n"
        "size=N/A time=02:15:30.750 bitrate=N/A speed=12x\n"
        "video:0kB audio:5000kB\n"
    )

    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout="",
            stderr=fake_stderr
        )
        duration = compiler._probe_duration(dummy_file)
        # 2*3600 + 15*60 + 30.750 = 7200 + 900 + 30.750 = 8130.75
        assert duration == pytest.approx(8130.75, rel=1e-5)



