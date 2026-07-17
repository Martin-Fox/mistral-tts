import os
import subprocess
from pathlib import Path
from typing import List

class AudioCompiler:
    """
    Handles stitching individual audio chunks into a single audiobook file.
    Uses FFmpeg for memory-efficient stitching on disk.
    """

    def __init__(self, pause_duration_s: float = 0.5):
        """
        Initialize the AudioCompiler.

        Args:
            pause_duration_s (float): Duration of silence to inject between chunks in seconds.
        """
        self.pause_duration_s = pause_duration_s

    def compile(self, chunk_paths: List[Path], output_path: Path):
        """
        Stitches audio chunks together using FFmpeg's concat demuxer.
        
        This method is memory-efficient as it doesn't load audio into RAM.
        """
        if not chunk_paths:
            raise ValueError("No audio chunks provided for compilation.")

        # Create a temporary file for the concat demuxer
        concat_file = output_path.with_suffix(".txt")
        
        # Probe the first chunk to match its audio properties for silence generation
        sample_rate, channels = self._probe_audio_properties(chunk_paths[0])
        
        # We need a silence file to inject pauses
        silence_file = output_path.parent / "silence.mp3"
        self._generate_silence(silence_file, sample_rate, channels)

        try:
            with open(concat_file, "w") as f:
                for i, chunk_path in enumerate(chunk_paths):
                    # Add the chunk
                    f.write(f"file '{chunk_path.absolute()}'\n")
                    # Add silence between chunks (but not after the last one)
                    if i < len(chunk_paths) - 1:
                        f.write(f"file '{silence_file.absolute()}'\n")

            # Run FFmpeg concat demuxer
            # -f concat: Use concat demuxer
            # -safe 0: Allow absolute paths
            # -af loudnorm: Apply loudness normalization to solve volume level fluctuations
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-af", "loudnorm", str(output_path)
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
        finally:
            # Clean up temporary files
            if concat_file.exists():
                concat_file.unlink()
            if silence_file.exists():
                silence_file.unlink()

    def _probe_audio_properties(self, file_path: Path) -> tuple[int, int]:
        """
        Probe the audio properties (sample_rate, channels) of a file using ffprobe.
        Defaults to (22050, 1) if probing fails.
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

    def _generate_silence(self, output_path: Path, sample_rate: int = 22050, channels: int = 1):
        """
        Generates a silent MP3 file of a specific duration matching the target audio properties.
        """
        channel_layout = "mono" if channels == 1 else "stereo"
        # Using an-null source and trim to generate silence
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", 
            "-i", f"anullsrc=r={sample_rate}:cl={channel_layout}",
            "-t", str(self.pause_duration_s), "-q:a", "9", str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
