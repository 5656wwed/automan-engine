"""Audio processing utilities using pydub."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydub import AudioSegment

from app.core.exceptions import AudioProcessingError
from app.utils.logger import get_logger

log = get_logger("utils.audio")


def _patch_pydub():
    """Ensure pydub can absolutely find ffmpeg and ffprobe."""
    try:
        from app.ffmpeg.detector import detect_ffmpeg
        import pydub.utils
        info = detect_ffmpeg()
        AudioSegment.converter = info.path
        ffprobe_path = info.path.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
        pydub.utils.get_prober_name = lambda: ffprobe_path
    except Exception:
        pass


def get_audio_duration(filepath: str | Path) -> float:
    """Get duration of an audio file in seconds."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise AudioProcessingError(str(filepath), "File does not exist.")

    try:
        from app.ffmpeg.wrapper import get_media_duration
        duration = get_media_duration(filepath)
        if duration <= 0:
            raise ValueError("FFprobe returned 0 or failed")
        return duration
    except Exception as e:
        raise AudioProcessingError(str(filepath), f"Could not read audio: {e}")


def convert_audio(
    input_path: str | Path,
    output_path: str | Path,
    format: str = "mp3",
    bitrate: str = "192k",
) -> Path:
    """Convert audio file to another format."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _patch_pydub()
    try:
        audio = AudioSegment.from_file(str(input_path))
        audio.export(str(output_path), format=format, bitrate=bitrate)
        log.debug(f"Converted {input_path.name} → {output_path.name} ({format})")
        return output_path
    except Exception as e:
        raise AudioProcessingError(str(input_path), f"Conversion failed: {e}")


import os

def add_silence_padding(
    input_path: str | Path,
    output_path: str | Path,
    padding_seconds: float = 0.5,
    position: str = "end",
) -> Path:
    """Add silence padding to an audio file using FFmpeg natively."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from app.ffmpeg.wrapper import _run_ffmpeg
        
        # We use anelay FFmpeg audio filter equivalent for silence padding.
        if padding_seconds <= 0:
            import shutil
            shutil.copy2(input_path, output_path)
            return output_path
            
        pad_ms = int(padding_seconds * 1000)
        
        if position == "start":
            filter_cmd = f"adelay={pad_ms}|{pad_ms}"
        elif position == "both":
            filter_cmd = f"adelay={pad_ms}|{pad_ms},apad=pad_dur={padding_seconds}"
        else: # end
            filter_cmd = f"apad=pad_dur={padding_seconds}"
            
        args = [
            "-i", str(input_path),
            "-af", filter_cmd,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(output_path)
        ]
        
        _run_ffmpeg(args, description=f"Add {padding_seconds}s silence")
        return output_path
    except Exception as e:
        raise AudioProcessingError(str(input_path), f"Silence padding failed: {e}")


def normalize_audio(
    input_path: str | Path,
    output_path: Optional[str | Path] = None,
    target_dbfs: float = -20.0,
) -> Path:
    """Normalize audio volume to a target dBFS level."""
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _patch_pydub()
    try:
        audio = AudioSegment.from_file(str(input_path))
        change_in_dbfs = target_dbfs - audio.dBFS
        normalized = audio.apply_gain(change_in_dbfs)

        fmt = output_path.suffix.lstrip(".") or "mp3"
        normalized.export(str(output_path), format=fmt)
        log.debug(f"Normalized {input_path.name} to {target_dbfs} dBFS")
        return output_path
    except Exception as e:
        raise AudioProcessingError(str(input_path), f"Normalization failed: {e}")
