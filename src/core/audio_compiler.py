import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

class AudioCompiler:
    """
    Handles stitching individual audio chunks into a single audiobook file.
    Uses FFmpeg for memory-efficient stitching on disk.
    """

    def __init__(self, pause_duration_s: float = 0.5, trailing_silence_s: float = 1.0):
        """
        Initialize the AudioCompiler.

        Args:
            pause_duration_s (float): Duration of silence to inject between chunks in seconds.
            trailing_silence_s (float): Duration of silence padding at the very end to prevent EOF truncation.
        """
        self.pause_duration_s = pause_duration_s
        self.trailing_silence_s = trailing_silence_s

    def _probe_duration(self, file_path: Path) -> float:
        """
        Probe the exact decoded playback duration of an audio file in seconds using FFmpeg null decoding.

        Args:
            file_path (Path): Path to the audio file.

        Returns:
            float: Duration in seconds.

        Raises:
            FileNotFoundError: If the audio file does not exist.
            RuntimeError: If FFmpeg decoding fails or returns an invalid duration.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found for duration probing: {file_path}")
        cmd = [
            "ffmpeg", "-nostats", "-v", "info",
            "-i", str(file_path),
            "-f", "null", "-"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30.0)
            matches = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", result.stderr)
            if not matches:
                raise ValueError(f"Could not parse duration from FFmpeg output for {file_path}")
            hours, minutes, seconds = matches[-1]
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception as e:
            raise RuntimeError(f"Failed to probe duration for {file_path}: {e}") from e

    def _probe_audio_properties(self, file_path: Path) -> tuple[int, int]:
        """
        Probe the audio properties (sample_rate, channels) of a file using ffprobe.
        Defaults to (22050, 1) if probing fails.

        Args:
            file_path (Path): Path to the audio file.

        Returns:
            tuple[int, int]: A tuple of (sample_rate, channels).
        """
        import json
        try:
            cmd = [
                "ffprobe", "-v", "error", 
                "-show_entries", "stream=sample_rate,channels", 
                "-of", "json", str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            if "streams" in data and len(data["streams"]) > 0:
                stream = data["streams"][0]
                sample_rate = int(stream.get("sample_rate", 22050))
                channels = int(stream.get("channels", 1))
                return sample_rate, channels
        except Exception:
            pass
        return 22050, 1

    def _generate_silence(self, output_path: Path, duration_s: Optional[float] = None, sample_rate: int = 22050, channels: int = 1):
        """
        Generates a silent MP3 file of a specific duration matching the target audio properties.

        Args:
            output_path (Path): Destination path for the generated silence file.
            duration_s (Optional[float]): Silence duration in seconds. Defaults to self.pause_duration_s if None.
            sample_rate (int): Audio sample rate in Hz.
            channels (int): Number of audio channels (1 for mono, 2 for stereo).
        """
        if duration_s is None:
            duration_s = self.pause_duration_s
        channel_layout = "mono" if channels == 1 else "stereo"
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", 
            "-i", f"anullsrc=r={sample_rate}:cl={channel_layout}",
            "-t", str(duration_s), "-q:a", "9", str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    def compile(self, chunk_paths: List[Path], output_path: Path) -> dict:
        """
        Stitches audio chunks together using FFmpeg's concat demuxer.
        Includes trailing silence padding to prevent EOF lookahead truncation
        and verifies final audio duration against expected total duration.

        Args:
            chunk_paths (List[Path]): Ordered list of paths to audio chunk MP3 files.
            output_path (Path): Destination path for the final stitched audiobook MP3 file.

        Returns:
            dict: Metadata summarizing the compilation with keys:
                - 'expected_duration' (float): Total expected duration in seconds (chunks + pauses + trailing silence).
                - 'output_duration' (float): Verified duration of the compiled output file in seconds.
                - 'total_chunks' (int): Total number of chunks processed.
                - 'total_chunks_duration' (float): Sum of individual chunk durations in seconds.
                - 'output_path' (Path): Path to the compiled audio file.

        Raises:
            ValueError: If chunk_paths list is empty.
            FileNotFoundError: If any chunk file does not exist on disk.
            RuntimeError: If any chunk is empty or invalid (<= 100 bytes), FFmpeg fails, output file is missing/empty,
                          or output duration is truncated by more than the allowed tolerance (4.0s).
        """
        if not chunk_paths:
            raise ValueError("No audio chunks provided for compilation.")

        # Ensure all chunk files exist and are not empty
        for idx, chunk_path in enumerate(chunk_paths):
            if not chunk_path.exists():
                raise FileNotFoundError(f"Chunk file not found: {chunk_path} (chunk {idx + 1}/{len(chunk_paths)})")
            if chunk_path.stat().st_size <= 100:
                raise RuntimeError(f"Chunk file is empty (<= 100 bytes): {chunk_path} (chunk {idx + 1}/{len(chunk_paths)})")

        # Calculate expected audio duration by probing durations of each chunk
        chunk_durations = [self._probe_duration(p) for p in chunk_paths]
        total_chunks_duration = sum(chunk_durations)
        pause_count = len(chunk_paths) - 1
        total_pauses_duration = pause_count * self.pause_duration_s
        expected_duration = total_chunks_duration + total_pauses_duration + self.trailing_silence_s

        # Ensure output directory exists before generating silence files or concat list
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temporary files for concat demuxer and silence
        unique_suffix = f"{os.getpid()}_{id(chunk_paths)}"
        concat_file = output_path.parent / f"concat_{output_path.stem}_{unique_suffix}.txt"
        silence_file = output_path.parent / f"silence_{unique_suffix}.mp3"
        trailing_silence_file = output_path.parent / f"trailing_silence_{unique_suffix}.mp3"

        # Probe the first chunk to match its audio properties for silence generation
        sample_rate, channels = self._probe_audio_properties(chunk_paths[0])

        if self.pause_duration_s > 0:
            self._generate_silence(silence_file, duration_s=self.pause_duration_s, sample_rate=sample_rate, channels=channels)
        if self.trailing_silence_s > 0:
            self._generate_silence(trailing_silence_file, duration_s=self.trailing_silence_s, sample_rate=sample_rate, channels=channels)

        try:
            with open(concat_file, "w") as f:
                for i, chunk_path in enumerate(chunk_paths):
                    f.write(f"file '{chunk_path.absolute()}'\n")
                    if i < len(chunk_paths) - 1 and self.pause_duration_s > 0:
                        f.write(f"file '{silence_file.absolute()}'\n")
                if self.trailing_silence_s > 0:
                    f.write(f"file '{trailing_silence_file.absolute()}'\n")

            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-af", "loudnorm", str(output_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"FFmpeg compilation failed to create output file: {output_path}")

            # Probe compiled output file duration with ffprobe
            output_duration = self._probe_duration(output_path)

            # Verification: output duration must match expected duration within a safe tolerance (e.g. 3-4 seconds)
            tolerance = 4.0
            if output_duration < (expected_duration - tolerance):
                raise RuntimeError(
                    f"Audiobook compilation truncated output: expected at least {expected_duration - tolerance:.2f}s "
                    f"(expected ~{expected_duration:.2f}s across {len(chunk_paths)} chunks), "
                    f"but final file is only {output_duration:.2f}s. "
                    f"Audio was truncated by {expected_duration - output_duration:.2f}s!"
                )

            return {
                "expected_duration": expected_duration,
                "output_duration": output_duration,
                "total_chunks": len(chunk_paths),
                "total_chunks_duration": total_chunks_duration,
                "output_path": output_path
            }

        finally:
            if concat_file.exists():
                try:
                    concat_file.unlink()
                except Exception:
                    pass
            if silence_file.exists():
                try:
                    silence_file.unlink()
                except Exception:
                    pass
            if trailing_silence_file.exists():
                try:
                    trailing_silence_file.unlink()
                except Exception:
                    pass
