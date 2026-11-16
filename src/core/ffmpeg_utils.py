"""
FFmpeg and FFprobe binary path resolution helper.
Supports standard system PATH, development workspaces, and bundled PyInstaller environments.
"""

import os
import shutil
import sys
from pathlib import Path


def resolve_binary(binary_name: str) -> str:
    """
    Dynamically resolves the path to an external binary (e.g. ffmpeg or ffprobe).

    Search hierarchy:
    1. PyInstaller extraction directory (sys._MEIPASS) and subfolders (bin/, tools/)
    2. Portable executable directory (sys.executable) and subfolders (bin/, tools/)
    3. Workspace / repository root directory and subfolders (bin/, tools/)
    4. System PATH (fallback to binary_name as-is for standard command invocation)
    """
    candidate_dirs: list[Path] = []

    # 1. PyInstaller bundled directory (onefile mode extraction)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_path = Path(meipass)
        candidate_dirs.extend([
            meipass_path / "bin",
            meipass_path / "tools",
            meipass_path,
        ])

    # 2. Directory containing the executable (portable / onedir mode)
    try:
        exe_path = Path(sys.executable).resolve()
        exe_dir = exe_path.parent
        if getattr(sys, "frozen", False):
            candidate_dirs.extend([
                exe_dir / "bin",
                exe_dir / "tools",
                exe_dir,
            ])
        else:
            if (exe_dir / "bin").is_dir():
                candidate_dirs.append(exe_dir / "bin")
    except Exception:
        pass

    # 3. Development project root directory (local bin/ or tools/ subfolders)
    try:
        project_root = Path(__file__).resolve().parent.parent.parent
        candidate_dirs.extend([
            project_root / "bin",
            project_root / "tools",
        ])
    except Exception:
        pass

    # Extensions to check based on platform
    extensions = [".exe", ""] if os.name == "nt" or sys.platform.startswith("win") else ["", ".exe"]

    # Search candidates in bundled or dedicated local folders
    for directory in candidate_dirs:
        try:
            if directory.is_dir():
                for ext in extensions:
                    candidate = directory / f"{binary_name}{ext}"
                    if candidate.is_file():
                        return str(candidate.resolve())
        except Exception:
            continue

    # 4. System PATH: check if available in PATH
    shutil.which(binary_name) or (
        shutil.which(f"{binary_name}.exe")
        if (os.name == "nt" or sys.platform.startswith("win"))
        else None
    )

    # Return command name for system PATH execution
    return binary_name


def get_ffmpeg_path() -> str:
    """Returns the resolved executable path or command for ffmpeg."""
    return resolve_binary("ffmpeg")


def get_ffprobe_path() -> str:
    """Returns the resolved executable path or command for ffprobe."""
    return resolve_binary("ffprobe")
