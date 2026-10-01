"""Transition engine — apply cinematic transitions between scene clips."""

from __future__ import annotations

import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from app.core.config import ExportSettings, TransitionType, get_config
from app.core.exceptions import TransitionError
from app.ffmpeg.detector import get_ffmpeg_path
from app.ffmpeg.wrapper import get_media_duration
from app.utils.logger import get_logger

log = get_logger("transitions.engine")

# Maximum clips per xfade batch — above this we chunk+concat to avoid
# FFmpeg memory exhaustion and command-line length limits.
_XFADE_CHUNK_SIZE = 15

# Map our TransitionType enums to FFmpeg xfade transition names
_XFADE_MAP = {
    TransitionType.FADE: "fade",
    TransitionType.DISSOLVE: "dissolve",
    TransitionType.DIP_TO_BLACK: "fadeblack",
    TransitionType.CINEMATIC_BLUR: "smoothleft",  # closest available xfade
    TransitionType.CROSS_ZOOM: "circleopen",      # closest available xfade
}


_RANDOM_POOL = [
    TransitionType.FADE,
    TransitionType.DISSOLVE,
    TransitionType.CROSS_ZOOM,
    TransitionType.DIP_TO_BLACK,
    TransitionType.CINEMATIC_BLUR,
]


def resolve_transition(
    scene_transition: Optional[str],
    project_transition: Optional[str],
) -> TransitionType:
    """Determine transition type for a scene boundary.

    Priority: per-scene override > project-level setting > config default.
    If the resolved value is "random", picks randomly from the cinematic pool.
    """
    raw = scene_transition or project_transition
    if not raw:
        raw = get_config().render.default_transition
        if isinstance(raw, TransitionType):
            raw = raw.value

    if not raw or raw == TransitionType.NONE.value:
        return TransitionType.NONE

    if raw == "random":
        return random.choice(_RANDOM_POOL)

    try:
        return TransitionType(raw)
    except ValueError:
        return TransitionType.FADE


def apply_transitions(
    clip_paths: list[Path],
    output_path: Path,
    transition_types: Optional[list[TransitionType]] = None,
    transition_duration: float = 0.5,
    export: Optional[ExportSettings] = None,
) -> Path:
    """Merge all clips with transitions into a single final video.

    Uses FFmpeg's xfade filter chained across all clips. For N clips there
    are N-1 transitions.

    Args:
        clip_paths: Ordered list of scene clip paths.
        output_path: Final output video path.
        transition_types: List of N-1 transitions, or None for all-same default.
        transition_duration: Duration of each transition in seconds.
        export: Export quality settings.

    Returns:
        Path to the merged output video.
    """
    if export is None:
        export = get_config().export

    if not clip_paths:
        raise TransitionError("merge", "No clips to merge.")

    if len(clip_paths) == 1:
        import shutil
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(clip_paths[0], output_path)
        log.info(f"Single scene — copied directly to {output_path.name}")
        return output_path

    n = len(clip_paths)

    # Default: all same transition
    if transition_types is None:
        default_t = get_config().render.default_transition
        if isinstance(default_t, str):
            try:
                default_t = TransitionType(default_t)
            except ValueError:
                default_t = TransitionType.FADE
        transition_types = [default_t] * (n - 1)

    if len(transition_types) != n - 1:
        log.warning(f"Expected {n - 1} transitions, got {len(transition_types)}. Padding with fade.")
        while len(transition_types) < n - 1:
            transition_types.append(TransitionType.FADE)

    log.info(f"Merging {n} clips | Transitions: {[t.value for t in transition_types]}")

    # If all transitions are NONE, just concatenate
    if all(t == TransitionType.NONE for t in transition_types):
        log.info("No transitions — using simple concatenation.")
        return _fallback_concat(clip_paths, output_path, export)

    # For large projects, chunk the merge to keep each FFmpeg call manageable.
    # Each chunk of ≤15 clips is merged with xfade, then all chunks are concat'd.
    if n > _XFADE_CHUNK_SIZE:
        return _chunked_merge(clip_paths, output_path, transition_types, transition_duration, export)

    return _xfade_merge(clip_paths, output_path, transition_types, transition_duration, export)


def _xfade_merge(
    clip_paths: list[Path],
    output_path: Path,
    transition_types: list[TransitionType],
    transition_duration: float,
    export: ExportSettings,
) -> Path:
    """Run a single FFmpeg xfade filter_complex over a small list of clips."""
    n = len(clip_paths)
    durations = [get_media_duration(p) for p in clip_paths]

    ffmpeg = get_ffmpeg_path()
    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", str(p)])

    filter_parts = []
    audio_parts = []
    cumulative_dur = 0.0
    offsets = []
    for i in range(n - 1):
        cumulative_dur += durations[i]
        offsets.append(max(cumulative_dur - transition_duration * (i + 1), 0))

    if n == 2:
        xfade_name = _XFADE_MAP.get(transition_types[0], "fade")
        filter_parts.append(
            f"[0:v][1:v]xfade=transition={xfade_name}:duration={transition_duration}:offset={offsets[0]}[vout]"
        )
        audio_parts.append(f"[0:a][1:a]acrossfade=d={transition_duration}[aout]")
    else:
        prev_v, prev_a = "[0:v]", "[0:a]"
        for i in range(n - 1):
            xfade_name = _XFADE_MAP.get(transition_types[i], "fade")
            next_v = f"[v{i}]" if i < n - 2 else "[vout]"
            next_a = f"[a{i}]" if i < n - 2 else "[aout]"
            filter_parts.append(
                f"{prev_v}[{i + 1}:v]xfade=transition={xfade_name}"
                f":duration={transition_duration}:offset={offsets[i]}{next_v}"
            )
            audio_parts.append(
                f"{prev_a}[{i + 1}:a]acrossfade=d={transition_duration}{next_a}"
            )
            prev_v, prev_a = next_v, next_a

    filter_complex = ";".join(filter_parts + audio_parts)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    cmd = [
        ffmpeg, "-y", "-hide_banner",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        *_video_flags(export),
        "-c:a", export.audio_codec, "-b:a", export.audio_bitrate,
        "-ar", "44100",
        "-ac", "2",
        "-pix_fmt", export.pixel_format,
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min per chunk
            creationflags=creationflags,
        )
        if result.returncode != 0:
            log.warning("xfade merge failed, falling back to concat.")
            return _fallback_concat(clip_paths, output_path, export)
        log.info(f"  xfade merged {n} clips → {output_path.name}")
        return output_path
    except subprocess.TimeoutExpired:
        log.warning(f"xfade timed out for {n} clips, falling back to concat.")
        return _fallback_concat(clip_paths, output_path, export)


def _chunked_merge(
    clip_paths: list[Path],
    output_path: Path,
    transition_types: list[TransitionType],
    transition_duration: float,
    export: ExportSettings,
) -> Path:
    """Merge large clip lists by splitting into chunks, xfading each chunk,
    then concatenating the chunk results. Keeps each FFmpeg call small."""
    n = len(clip_paths)
    chunk_size = _XFADE_CHUNK_SIZE
    log.info(f"  Large project ({n} clips) — chunked merge (chunk_size={chunk_size})")

    if clip_paths:
        work = clip_paths[0].parent / "_chunks"
    else:
        work = Path(tempfile.gettempdir()) / "autoscene_tmp" / "_chunks"
    work.mkdir(parents=True, exist_ok=True)

    chunk_outputs: list[Path] = []
    idx = 0
    chunk_num = 0
    while idx < n:
        end = min(idx + chunk_size, n)
        chunk_clips = clip_paths[idx:end]
        # transitions[idx] is between clip[idx] and clip[idx+1], so for this
        # chunk we need transitions[idx .. end-2]
        chunk_trans = transition_types[idx:end - 1]

        chunk_out = work / f"_chunk_{chunk_num:04d}.mp4"
        log.info(f"  Chunk {chunk_num + 1}: clips {idx + 1}–{end}")

        if len(chunk_clips) == 1:
            import shutil
            shutil.copy2(chunk_clips[0], chunk_out)
        elif all(t == TransitionType.NONE for t in chunk_trans):
            _fallback_concat(chunk_clips, chunk_out, export)
        else:
            _xfade_merge(chunk_clips, chunk_out, chunk_trans, transition_duration, export)

        chunk_outputs.append(chunk_out)
        idx = end
        chunk_num += 1

    log.info(f"  Concatenating {len(chunk_outputs)} chunks into final video...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _fallback_concat(chunk_outputs, output_path, export)

    # Clean up chunk temp files
    for p in chunk_outputs:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    log.info(f"  Chunked merge complete → {output_path.name}")
    return output_path


def _fallback_concat(
    clip_paths: list[Path],
    output_path: Path,
    export: ExportSettings,
) -> Path:
    """Fallback: simple concatenation without transitions if xfade fails."""
    from app.ffmpeg.wrapper import concatenate_videos
    concatenate_videos([str(p) for p in clip_paths], str(output_path), export)
    return output_path

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

