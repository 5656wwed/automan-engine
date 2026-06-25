"""FFmpeg command builder and executor — the core video engine."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from app.core.config import ExportSettings, get_config
from app.core.exceptions import RenderError
from app.ffmpeg.detector import get_ffmpeg_path, get_ffprobe_path
from app.utils.logger import get_logger

log = get_logger("ffmpeg.wrapper")


# ---------------------------------------------------------------------------
# Duration helpers
import sys

def get_media_duration(filepath: str | Path) -> float:
    """Get duration of a media file in seconds using ffprobe."""
    ffprobe = get_ffprobe_path()
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(filepath),
    ]
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=20, 
            stdin=subprocess.DEVNULL,
            creationflags=creationflags
        )
        dur = float(result.stdout.strip())
        return dur
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning(f"Could not get duration for {filepath}: {e}")
        return 0.0


# ---------------------------------------------------------------------------
# FFmpeg command runner
# ---------------------------------------------------------------------------
def _run_ffmpeg(
    args: list[str],
    description: str = "FFmpeg",
    progress_callback: Optional[Callable[[float], None]] = None,
    total_duration: Optional[float] = None,
) -> None:
    """Run an FFmpeg command synchronously with optional progress tracking."""
    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-y", "-hide_banner"] + args
    log.debug(f"[{description}] Running: {' '.join(cmd)}")

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,  # Avoid deadlock
            stderr=subprocess.PIPE,
            universal_newlines=True,
            creationflags=creationflags,
        )

        stderr_output = []
        for line in process.stderr:
            stderr_output.append(line)
            # Parse progress from time= in stderr
            if progress_callback and total_duration and "time=" in line:
                match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                if match:
                    h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
                    current = h * 3600 + m * 60 + s
                    progress = min(current / total_duration, 1.0)
                    progress_callback(progress)

        process.wait()

        if process.returncode != 0:
            error_text = "".join(stderr_output[-20:])  # Last 20 lines
            raise RenderError(description, f"FFmpeg exited with code {process.returncode}\n{error_text}")

        log.info(f"[{description}] Completed successfully.")

    except FileNotFoundError:
        raise RenderError(description, "FFmpeg binary not found.")


async def _run_ffmpeg_async(
    args: list[str],
    description: str = "FFmpeg",
    progress_callback: Optional[Callable[[float], None]] = None,
    total_duration: Optional[float] = None,
) -> None:
    """Run FFmpeg command asynchronously."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _run_ffmpeg(args, description, progress_callback, total_duration),
    )


# ---------------------------------------------------------------------------
# High-level video operations
# ---------------------------------------------------------------------------
def mp4_to_clip(
    video_path: str | Path,
    output_path: str | Path,
    duration: float,
    export: ExportSettings | None = None,
    overlay_filters: Optional[list[str]] = None,
) -> None:
    """Scale, pad, time-stretch (if short), and trim an MP4 to scene duration.

    - MP4 longer than duration  → trimmed with -t (fast, no re-timing).
    - MP4 shorter than duration → slowed via setpts so it fills exactly
      duration seconds. No frame interpolation; timestamps are scaled.
    Audio is always stripped (-an); add_audio_to_video mixes TTS + the
    original MP4 audio at attenuated volume separately.
    """
    if export is None:
        export = get_config().export

    fps = export.fps
    width = export.width
    height = export.height

    src_duration = get_media_duration(video_path)

    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
    ]

    if src_duration > 0 and src_duration < duration:
        ratio = duration / src_duration
        filters.append(f"setpts={ratio:.6f}*PTS")
        log.info(
            f"  [mp4_to_clip] {Path(video_path).name}: "
            f"{src_duration:.1f}s → stretching to {duration:.1f}s (×{ratio:.2f})"
        )
    else:
        log.info(
            f"  [mp4_to_clip] {Path(video_path).name}: "
            f"{src_duration:.1f}s → trimming to {duration:.1f}s"
        )

    filters.append(f"fps={fps}")

    if overlay_filters:
        filters.extend(overlay_filters)

    filter_str = ",".join(filters)

    args = [
        "-i", str(video_path),
        "-vf", filter_str,
        "-t", str(duration),
        "-an",
        "-c:v", export.codec,
        "-crf", str(export.crf),
        "-preset", export.preset_speed,
        "-pix_fmt", export.pixel_format,
        "-r", str(fps),
        str(output_path),
    ]
    desc = f"Video->Clip ({Path(video_path).name})"
    try:
        _run_ffmpeg(args, description=desc)
    except RenderError as e:
        if "malloc" not in str(e).lower():
            raise
        import time
        log.warning(f"  ⚠ malloc failure encoding {Path(video_path).name} — retrying with low-memory x264 params")
        time.sleep(2)
        low_mem_args = args[:-1] + [
            "-x264-params", "ref=1:bframes=0:rc-lookahead=0:threads=1",
            args[-1],
        ]
        _run_ffmpeg(low_mem_args, description=f"{desc} [low-mem]")


def image_to_video(
    image_path: str | Path,
    output_path: str | Path,
    duration: float,
    motion_filter: str = "",
    export: ExportSettings | None = None,
    overlay_filters: Optional[list[str]] = None,
) -> None:
    """Convert a single image to a video clip with optional motion effect and text overlay."""
    if export is None:
        export = get_config().export

    fps = export.fps
    width = export.width
    height = export.height

    # Build video filter chain
    filters = []

    if motion_filter:
        filters.append(motion_filter)
    else:
        # Default: static image scaled to fill
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")

    if overlay_filters:
        filters.extend(overlay_filters)

    filter_str = ",".join(filters)

    args = [
        "-loop", "1",
        "-i", str(image_path),
        "-vf", filter_str,
        "-t", str(duration),
        "-c:v", export.codec,
        "-crf", str(export.crf),
        "-preset", export.preset_speed,
        "-pix_fmt", export.pixel_format,
        "-r", str(fps),
        str(output_path),
    ]

    desc = f"Image->Video ({Path(image_path).name})"
    try:
        _run_ffmpeg(args, description=desc)
    except RenderError as e:
        if "malloc" not in str(e).lower():
            raise
        import time
        log.warning(f"  ⚠ malloc failure encoding {Path(image_path).name} — retrying with low-memory x264 params")
        time.sleep(2)
        low_mem_args = args[:-1] + [
            "-x264-params", "ref=1:bframes=0:rc-lookahead=0:threads=1",
            args[-1],
        ]
        _run_ffmpeg(low_mem_args, description=f"{desc} [low-mem]")


def add_audio_to_video(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    export: ExportSettings | None = None,
    sfx_path: Optional[Path] = None,
    sfx_delay_ms: int = 0,
    sfx_volume: float = 0.55,
    duration: Optional[float] = None,
    bg_audio_path: Optional[Path] = None,
    bg_audio_volume: float = 0.15,
    voice_volume: float = 1.0,
) -> None:
    """Overlay audio onto a video, optionally mixing SFX and/or MP4 background audio.

    bg_audio_path: original MP4 audio track, attenuated to bg_audio_volume
                   (0.15 ≈ −16.5 dB, roughly 15% of original level).
    """
    if export is None:
        export = get_config().export

    has_sfx = bool(sfx_path and Path(sfx_path).exists())
    has_bg  = bool(bg_audio_path and Path(bg_audio_path).exists())

    if has_sfx and has_bg:
        # MP4 scene with overlay: voice + sfx whoosh + mp4 bg audio
        # Inputs: 0=video  1=TTS  2=sfx  3=mp4
        af = (
            f"[2:a]adelay={sfx_delay_ms}|{sfx_delay_ms},volume={sfx_volume}[sfx];"
            f"[3:a]volume={bg_audio_volume:.3f}[bg];"
            f"[1:a]adelay=200|200,volume={voice_volume:.3f}[voice];"
            f"[sfx][voice][bg]amix=inputs=3:duration=longest"
        )
        if duration:
            af += f",apad=whole_dur={duration:.3f}"
        af += "[a]"
        args = [
            "-i", str(video_path),
            "-i", str(audio_path),
            "-i", str(sfx_path),
            "-i", str(bg_audio_path),
            "-filter_complex", af,
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", export.audio_codec,
            "-b:a", export.audio_bitrate,
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
            str(output_path),
        ]

    elif has_sfx:
        # Image scene with overlay: voice + sfx whoosh
        # Inputs: 0=video  1=TTS  2=sfx
        af = (
            f"[2:a]adelay={sfx_delay_ms}|{sfx_delay_ms},volume={sfx_volume}[sfx];"
            f"[1:a]adelay=200|200,volume={voice_volume:.3f}[voice];"
            f"[sfx][voice]amix=inputs=2:duration=longest"
        )
        if duration:
            af += f",apad=whole_dur={duration:.3f}"
        af += "[a]"
        args = [
            "-i", str(video_path),
            "-i", str(audio_path),
            "-i", str(sfx_path),
            "-filter_complex", af,
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", export.audio_codec,
            "-b:a", export.audio_bitrate,
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
            str(output_path),
        ]

    elif has_bg:
        # MP4 scene without overlay: voice (full) + mp4 bg audio (attenuated)
        # Inputs: 0=video  1=TTS  2=mp4
        af = (
            f"[2:a]volume={bg_audio_volume:.3f}[bg];"
            f"[1:a]volume={voice_volume:.3f}[voice];"
            f"[voice][bg]amix=inputs=2:duration=first:normalize=0[a]"
        )
        args = [
            "-i", str(video_path),
            "-i", str(audio_path),
            "-i", str(bg_audio_path),
            "-filter_complex", af,
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", export.audio_codec,
            "-b:a", export.audio_bitrate,
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
            str(output_path),
        ]

    else:
        # Plain: video + TTS voice only
        if voice_volume != 1.0:
            args = [
                "-i", str(video_path),
                "-i", str(audio_path),
                "-filter_complex", f"[1:a]volume={voice_volume:.3f}[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", export.audio_codec,
                "-b:a", export.audio_bitrate,
                "-ar", "44100",
                "-ac", "2",
                "-shortest",
                str(output_path),
            ]
        else:
            args = [
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-c:a", export.audio_codec,
                "-b:a", export.audio_bitrate,
                "-ar", "44100",
                "-ac", "2",
                "-shortest",
                str(output_path),
            ]

    _run_ffmpeg(args, description=f"Add audio ({Path(audio_path).name})")


def concatenate_videos(
    video_paths: list[str | Path],
    output_path: str | Path,
    export: ExportSettings | None = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    copy_streams: bool = True,
) -> None:
    """Concatenate multiple video clips into one final video.

    Uses stream-copy by default (no re-encode) — much faster and avoids
    disk-full / muxing failures on large projects. Set copy_streams=False
    to force a full re-encode (rarely needed).
    """
    if export is None:
        export = get_config().export

    if not video_paths:
        raise RenderError("concatenate", "No video files to concatenate.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Use a concat list in the same folder as the output
    concat_file = output.parent / "_concat_list.txt"
    try:
        with open(concat_file, "w", encoding="utf-8") as f:
            for vp in video_paths:
                safe_path = str(Path(vp).resolve()).replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        total_dur = sum(get_media_duration(vp) for vp in video_paths)

        if copy_streams:
            # Stream copy: instant, no quality loss, no disk overhead
            args = [
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path),
            ]
        else:
            args = [
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", export.codec,
                "-crf", str(export.crf),
                "-preset", export.preset_speed,
                "-c:a", export.audio_codec,
                "-b:a", export.audio_bitrate,
                "-pix_fmt", export.pixel_format,
                str(output_path),
            ]

        _run_ffmpeg(
            args,
            description="Final merge",
            progress_callback=progress_callback,
            total_duration=total_dur,
        )
    finally:
        if concat_file.exists():
            concat_file.unlink()


def apply_transition_between(
    video_a: str | Path,
    video_b: str | Path,
    output_path: str | Path,
    transition_filter: str = "fade",
    transition_duration: float = 0.5,
    export: ExportSettings | None = None,
) -> None:
    """Apply a transition filter between two video clips."""
    if export is None:
        export = get_config().export

    dur_a = get_media_duration(video_a)
    dur_b = get_media_duration(video_b)
    offset = max(dur_a - transition_duration, 0)

    if transition_filter == "fade":
        # xfade filter
        args = [
            "-i", str(video_a),
            "-i", str(video_b),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={transition_duration}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={transition_duration}[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", export.codec,
            "-crf", str(export.crf),
            "-preset", export.preset_speed,
            "-c:a", export.audio_codec,
            "-pix_fmt", export.pixel_format,
            str(output_path),
        ]
    elif transition_filter in ("dissolve", "circlecrop", "smoothleft", "smoothright"):
        args = [
            "-i", str(video_a),
            "-i", str(video_b),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition={transition_filter}:duration={transition_duration}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={transition_duration}[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", export.codec,
            "-crf", str(export.crf),
            "-preset", export.preset_speed,
            "-c:a", export.audio_codec,
            "-pix_fmt", export.pixel_format,
            str(output_path),
        ]
    else:
        # Fallback: simple concatenation
        concatenate_videos([str(video_a), str(video_b)], str(output_path), export)
        return

    _run_ffmpeg(args, description=f"Transition ({transition_filter})")


def mix_background_music(
    video_path: str | Path,
    music_path: str | Path,
    output_path: str | Path,
    music_volume: float = 0.20,
    export: ExportSettings | None = None,
) -> None:
    """Mix looping background music into a video, blending under the voiceover."""
    if export is None:
        export = get_config().export

    # voice stays full volume; music is attenuated; normalize=0 preserves levels
    af = (
        f"[0:a]volume=1.0[voice];"
        f"[1:a]volume={music_volume:.3f}[bgm];"
        f"[voice][bgm]amix=inputs=2:duration=first:normalize=0[aout]"
    )

    args = [
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", af,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", export.audio_codec,
        "-b:a", export.audio_bitrate,
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        str(output_path),
    ]

    _run_ffmpeg(args, description=f"BG music ({Path(music_path).name})")


def scale_image(
    image_path: str | Path,
    output_path: str | Path,
    width: int,
    height: int,
) -> None:
    """Scale/pad an image to exact dimensions."""
    args = [
        "-i", str(image_path),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        str(output_path),
    ]
    _run_ffmpeg(args, description=f"Scale image ({Path(image_path).name})")
