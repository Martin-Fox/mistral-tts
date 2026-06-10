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
        
        # We need a silence file to inject pauses
        silence_file = output_path.parent / "silence.mp3"
        self._generate_silence(silence_file)

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
            # -c copy: Copy streams without re-encoding (very fast)
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-c", "copy", str(output_path)
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
        finally:
            # Clean up temporary files
            if concat_file.exists():
                concat_file.unlink()
            if silence_file.exists():
                silence_file.unlink()

    def _generate_silence(self, output_path: Path):
        """
        Generates a silent MP3 file of a specific duration.
        """
        # Using an-null source and trim to generate silence
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(self.pause_duration_s), "-q:a", "9", str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
