"""FFmpeg command builder and executor — the core video engine."""

from __future__ import annotations

import asyncio
import os
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

def _letterbox_video() -> bool:
    """True = pad an off-ratio video clip with black bars instead of filling the
    frame. Default is False (fill/crop), matching what stills do."""
    return os.environ.get("AUTOMAN_LETTERBOX_VIDEO", "0").strip().lower() in ("1", "true", "yes")


def has_audio_stream(filepath: str | Path) -> bool:
    """True when the media file carries an audio track.

    A silent source clip (common with AI-generated b-roll) must not be used as a
    background-audio input: the amix filtergraph would ask for `[N:a]` on a
    stream that does not exist and the whole scene render fails.
    """
    try:
        from app.ffmpeg.detector import get_ffprobe_path
        ffprobe = get_ffprobe_path()
        proc = subprocess.run(
            [str(ffprobe), "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(filepath)],
            capture_output=True, text=True,
        )
        return bool((proc.stdout or "").strip())
    except Exception:
        return False


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
    short_policy: str = "slow",
) -> None:
    """Scale, fill, retime (if short) and trim an MP4 to exactly `duration`.

    - MP4 longer than duration → trimmed with -t (fast, no re-timing).
    - MP4 shorter than duration → `short_policy` decides what fills the gap:
        "slow" (default) — retime with setpts so the clip plays a little slower and
            lasts the whole beat. The picture never repeats and never freezes; a
            1.2–1.6x stretch is invisible on b-roll. Stretches beyond 2x would
            judder, so past that it stretches 2x and holds the rest.
        "hold" — freeze on the last frame for the shortfall.
        "loop" — repeat the clip from the start (the old default; the eye reads the
            restart as "the last shot came back" right before the cut).
    Audio is always stripped (-an); add_audio_to_video mixes TTS + the
    original MP4 audio at attenuated volume separately.
    """
    if export is None:
        export = get_config().export

    fps = export.fps
    width = export.width
    height = export.height

    src_duration = get_media_duration(video_path)

    # Match the still-image path: FILL the frame (scale to cover + centre crop)
    # so a clip whose aspect ratio isn't exactly the export ratio never shows
    # black bars — bars are the quickest way for a video clip to look different
    # from the stills around it. $AUTOMAN_LETTERBOX_VIDEO=1 restores the old
    # pad-with-black behaviour.
    if _letterbox_video():
        filters = [
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        ]
    else:
        filters = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
        ]

    input_loop = []
    hold_last = 0.0
    retime = 0.0
    policy = str(short_policy or "slow").strip().lower()
    if policy not in ("slow", "hold", "loop"):
        policy = "slow"
    _name = Path(video_path).name

    if src_duration > 0 and src_duration < duration:
        shortfall = duration - src_duration
        if policy == "loop":
            input_loop = ["-stream_loop", "-1"]
            log.info(
                f"  [mp4_to_clip] {_name}: {src_duration:.1f}s < beat {duration:.1f}s "
                f"→ repeating the clip to fill (Repeat the clip is selected)"
            )
        elif policy == "hold" or shortfall <= max(0.75, src_duration * 0.15):
            # Tiny gap (e.g. an 8.0s clip in an 8.2s beat) is ALWAYS held: a loop
            # restarts the clip and the eye reads it as the shot coming back.
            hold_last = shortfall
            log.info(
                f"  [mp4_to_clip] {_name}: {src_duration:.1f}s < beat {duration:.1f}s "
                f"→ holding last frame for {shortfall:.2f}s"
            )
        else:
            # Slow it down to fill the beat: continuous motion, no repeat, no freeze.
            retime = duration / src_duration
            if retime > 2.0:
                retime = 2.0
                hold_last = max(0.0, duration - src_duration * retime)
            log.info(
                f"  [mp4_to_clip] {_name}: {src_duration:.1f}s < beat {duration:.1f}s "
                f"→ slowing to {retime:.2f}x to fill (no repeat)"
                + (f", then holding {hold_last:.2f}s" if hold_last > 0.01 else "")
            )
    else:
        log.info(
            f"  [mp4_to_clip] {_name}: {src_duration:.1f}s → trimming to {duration:.1f}s"
        )

    if retime > 0:
        filters.append(f"setpts=PTS*{retime:.6f}")
    filters.append(f"fps={fps}")

    if hold_last > 0:
        filters.append(f"tpad=stop_mode=clone:stop_duration={hold_last:.3f}")

    if overlay_filters:
        filters.extend(overlay_filters)

    filter_str = ",".join(filters)

    args = (
        input_loop
        + [
            "-i", str(video_path),
            "-vf", filter_str,
            "-t", str(duration),
            "-an",
            *_video_flags(export),
            "-pix_fmt", export.pixel_format,
            "-r", str(fps),
            str(output_path),
        ]
    )
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
        *_video_flags(export),
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
    music_path: Optional[Path] = None,
    music_volume: float = 0.3,
    mute_bg: bool = False,
    music_loop: bool = True,
) -> None:
    """Overlay narration onto a video, optionally mixing SFX, the clip's own
    audio (bg), and/or an uploaded background-music track.

    Inputs (added only when present):
        0 = video, 1 = voice(TTS), 2 = sfx, 3 = clip-bg, 4 = music
    `mute_bg=True` drops the clip's original audio entirely.
    `music_path` is a background-music file mixed at `music_volume`;
    `music_loop=True` loops it (via -stream_loop) so it covers the full clip.
    """
    if export is None:
        export = get_config().export

    has_sfx = bool(sfx_path and Path(sfx_path).exists())
    has_bg  = bool(bg_audio_path and Path(bg_audio_path).exists()) and not mute_bg
    has_music = bool(music_path and Path(music_path).exists())

    inputs = ["-i", str(video_path), "-i", str(audio_path)]
    parts = [f"[1:a]adelay=200|200,volume={voice_volume:.3f}[voice]"]
    mix = ["[voice]"]

    if has_sfx:
        idx = len(inputs) // 2
        inputs += ["-i", str(sfx_path)]
        parts.append(f"[{idx}:a]adelay={sfx_delay_ms}|{sfx_delay_ms},volume={sfx_volume:.3f}[sfx]")
        mix.append("[sfx]")
    if has_bg:
        idx = len(inputs) // 2
        inputs += ["-i", str(bg_audio_path)]
        parts.append(f"[{idx}:a]volume={bg_audio_volume:.3f}[bg]")
        mix.append("[bg]")
    if has_music:
        idx = len(inputs) // 2
        if music_loop:
            inputs += ["-stream_loop", "-1"]
        inputs += ["-i", str(music_path)]
        parts.append(f"[{idx}:a]volume={music_volume:.3f}[music]")
        mix.append("[music]")

    if len(mix) == 1:
        # only voice
        af = f"[1:a]adelay=200|200,volume={voice_volume:.3f}"
    else:
        af = ";".join(parts) + f";{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0"
    if duration:
        af += f",apad=whole_dur={duration:.3f}"
    af += "[a]"

    args = inputs + [
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
                *_video_flags(export),
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
            *_video_flags(export),
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
            *_video_flags(export),
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

_AUTO_CODEC_CACHE: list[str | None] = [None]

def _resolve_codec(export):
    """Return the video codec to use.

    Explicit AUTOMAN_CODEC (or project) value wins. When codec is "auto",
    probe the ffmpeg binary ONCE with real 1-frame encodes and pick the best
    hardware encoder that actually works: h264_nvenc (NVIDIA) >
    h264_qsv (Intel QSV) > h264_amf (AMD) > libx264 (CPU). Checking the
    encoder list is NOT enough - full ffmpeg builds list nvenc/qsv even when
    no such GPU exists, so each candidate is verified with a real encode."""
    codec = (export.codec or "libx264").lower()
    if codec != "auto":
        return codec
    if _AUTO_CODEC_CACHE[0] is not None:
        return _AUTO_CODEC_CACHE[0]
    import shutil as _sh, subprocess as _sp, tempfile as _tf
    ff = getattr(export, "ffmpeg_path", None) or _sh.which("ffmpeg") or "ffmpeg"
    base = ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=320x180:rate=15", "-frames:v", "1", "-y"]
    candidates = [("h264_nvenc", ["-rc", "vbr", "-cq", "28", "-preset", "p4"]),
                  ("h264_qsv", ["-global_quality", "28", "-preset", "medium", "-look_ahead", "0"]),
                  ("h264_amf", ["-rc", "cqp", "-qp_i", "28", "-qp_p", "28", "-quality", "balanced"])]
    for cand, extra in candidates:
        tmp = _tf.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.close()
        try:
            r = _sp.run([ff] + base + ["-c:v", cand] + extra + [tmp.name],
                        capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                _AUTO_CODEC_CACHE[0] = cand
                print(f"[automan] codec auto-detect -> {cand}")
                return cand
        except Exception:
            pass
        finally:
            try:
                import os as _os
                _os.unlink(tmp.name)
            except Exception:
                pass
    _AUTO_CODEC_CACHE[0] = "libx264"
    print("[automan] codec auto-detect -> libx264 (no working hardware encoder)")
    return _AUTO_CODEC_CACHE[0]


def _video_flags(export):
    """Return codec flags for export. Uses NVENC flags when codec is an nvenc
    codec (h264_nvenc / hevc_nvenc), QSV flags for Intel Quick Sync
    (h264_qsv / hevc_qsv), AMF flags for AMD (h264_amf), otherwise the
    original x264 flags. Honors codec="auto" via _resolve_codec."""
    codec = _resolve_codec(export)
    if "nvenc" in codec:
        q = getattr(export, "quality", None)
        qv = getattr(q, "value", None) if q is not None else None
        nv_preset = {"low": "p1", "medium": "p3", "high": "p4", "ultra": "p6"}.get(qv, "p4")
        return ["-c:v", codec, "-rc", "vbr", "-cq", str(export.crf),
                "-b:v", "0", "-preset", nv_preset]
    if "qsv" in codec:
        q = getattr(export, "quality", None)
        qv = getattr(q, "value", None) if q is not None else None
        qsv_preset = {"low": "veryfast", "medium": "medium", "high": "slow", "ultra": "veryslow"}.get(qv, "medium")
        return ["-c:v", codec, "-global_quality", str(export.crf),
                "-preset", qsv_preset, "-look_ahead", "0"]
    if "amf" in codec:
        q = getattr(export, "quality", None)
        qv = getattr(q, "value", None) if q is not None else None
        amf_preset = {"low": "speed", "medium": "balanced", "high": "quality", "ultra": "quality"}.get(qv, "balanced")
        return ["-c:v", codec, "-rc", "cqp", "-qp_i", str(export.crf),
                "-qp_p", str(export.crf), "-quality", amf_preset]
    return ["-c:v", codec, "-crf", str(export.crf), "-preset", export.preset_speed]

