"""FFmpeg detection and installation guidance."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import get_config
from app.core.exceptions import FFmpegNotFoundError
from app.utils.logger import get_logger

log = get_logger("ffmpeg.detector")


@dataclass
class FFmpegInfo:
    """Information about an installed FFmpeg binary."""
    path: str
    version: str
    has_libx264: bool = True
    has_aac: bool = True


def _run_ffmpeg_check(ffmpeg_path: str) -> Optional[FFmpegInfo]:
    """Try running ffmpeg -version and parse the result."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = result.stdout
            # Parse version from first line
            version_line = output.split("\n")[0] if output else "unknown"
            version = "unknown"
            if "version" in version_line.lower():
                parts = version_line.split()
                for i, p in enumerate(parts):
                    if p.lower() == "version" and i + 1 < len(parts):
                        version = parts[i + 1]
                        break

            has_x264 = "libx264" in output
            has_aac = "aac" in output.lower()

            return FFmpegInfo(
                path=ffmpeg_path,
                version=version,
                has_libx264=has_x264,
                has_aac=has_aac,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


# Global cache
_cached_info: Optional[FFmpegInfo] = None

def detect_ffmpeg() -> FFmpegInfo:
    """Detect FFmpeg installation. Raises FFmpegNotFoundError if not found."""
    global _cached_info
    if _cached_info:
        return _cached_info

    config = get_config()
    searched: list[str] = []

    # 1. Check config path
    if config.ffmpeg_path:
        searched.append(config.ffmpeg_path)
        info = _run_ffmpeg_check(config.ffmpeg_path)
        if info:
            log.info(f"FFmpeg found at configured path: {info.path} (v{info.version})")
            _cached_info = info
            return info

    # 2. Check PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        searched.append(ffmpeg_in_path)
        info = _run_ffmpeg_check(ffmpeg_in_path)
        if info:
            log.info(f"FFmpeg found in PATH: {info.path} (v{info.version})")
            _cached_info = info
            return info

    # 3. Check common Windows locations
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        str(Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe"),
        str(Path.home() / "scoop" / "shims" / "ffmpeg.exe"),
    ]

    for path in common_paths:
        searched.append(path)
        info = _run_ffmpeg_check(path)
        if info:
            log.info(f"FFmpeg found at: {info.path} (v{info.version})")
            _cached_info = info
            return info

    raise FFmpegNotFoundError(searched_paths=searched)


def get_ffmpeg_path() -> str:
    """Get the path to the FFmpeg binary. Cached after first detection."""
    info = detect_ffmpeg()
    return info.path


def get_ffprobe_path() -> str:
    """Get the path to ffprobe (assumed alongside ffmpeg)."""
    ffmpeg = get_ffmpeg_path()
    ffprobe = Path(ffmpeg).parent / "ffprobe.exe"
    if ffprobe.exists():
        return str(ffprobe)
    # Fallback: try PATH
    in_path = shutil.which("ffprobe")
    if in_path:
        return in_path
    return "ffprobe"


INSTALLATION_GUIDE = """
╔══════════════════════════════════════════════════════════════╗
║              FFmpeg Installation Guide (Windows)            ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Option 1: Chocolatey (Recommended)                         ║
║    choco install ffmpeg                                      ║
║                                                              ║
║  Option 2: Scoop                                            ║
║    scoop install ffmpeg                                      ║
║                                                              ║
║  Option 3: Manual                                           ║
║    1. Download from https://ffmpeg.org/download.html        ║
║    2. Extract to C:\\ffmpeg                                   ║
║    3. Add C:\\ffmpeg\\bin to your system PATH                  ║
║    4. Restart your terminal                                  ║
║                                                              ║
║  Verify: ffmpeg -version                                    ║
╚══════════════════════════════════════════════════════════════╝
"""
