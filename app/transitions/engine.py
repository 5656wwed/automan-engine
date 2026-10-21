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
from app.ffmpeg.detector import get_ffmpeg_path, get_ffprobe_path
from app.ffmpeg.wrapper import get_media_duration
from app.utils.logger import get_logger

log = get_logger("transitions.engine")

# Maximum clips per xfade batch — above this we chunk+concat to avoid
# FFmpeg memory exhaustion and command-line length limits.
#
# Do NOT raise this back to 15. On the ffmpeg builds tested here (9.0.1), a
# xfade chain nested more than one level deep silently drops the tail of the
# VIDEO stream while keeping the audio: a 15-clip chunk of 133 s came out with
# 31 s of picture and the player froze on its last frame for the remaining
# 61 s (exactly the "an image stays stuck for a minute" complaint). Three clips
# = two xfade steps = one nesting level, which is correct (measured 25.40 s for
# 25.37 s of input). Every chunk is duration-verified after merging anyway.
_XFADE_CHUNK_SIZE = 3

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


def _stream_durations(path: Path) -> tuple[float, float]:
    """(video, audio) stream durations of a container — 0.0 when a stream is absent.

    Reads the STREAM durations, not the container's: a container can claim 90 s
    while its video stream really holds 31 s of frames.
    """
    ffprobe = get_ffprobe_path()
    video = audio = 0.0
    try:
        r = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "stream=codec_type,duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=180,
        )
        for line in (r.stdout or "").splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            kind, raw = parts[0], parts[1]
            try:
                dur = float(raw)
            except ValueError:
                continue
            if kind == "video":
                video = max(video, dur)
            elif kind == "audio":
                audio = max(audio, dur)
    except Exception:
        pass
    return video, audio


def _merge_is_sound(path: Path, tolerance: float = 1.0) -> tuple[bool, float, float]:
    """True when a merged file's video stream is not shorter than its audio.

    A chained xfade silently drops the tail of the video stream on some builds
    while the audio keeps going: the container looks right (audio length) but the
    picture FREEZES on its last frame for the missing seconds — the classic
    "some images stay stuck for a minute" complaint. Anything merged here is
    verified before it is accepted.
    """
    video, audio = _stream_durations(path)
    if video <= 0.0 or audio <= 0.0:
        return True, video, audio  # cannot judge (silent or video-only) — leave it
    return video >= audio - tolerance, video, audio



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

    # DIP TO BLACK is done INSIDE each scene (the picture fades out at the tail and
    # back in at the head — see scene_renderer), so the merge itself must not
    # overlap anything: an xfade would re-show the outgoing shot and swallow
    # narration. Concatenate instead: exact timeline, nothing repeats.
    if all(t in (TransitionType.NONE, TransitionType.DIP_TO_BLACK) for t in transition_types):
        log.info("Dip to black — concatenating (dips are baked into each scene).")
        return _fallback_concat(clip_paths, output_path, export)

    # For large projects, chunk the merge to keep each FFmpeg call manageable.
    # Each chunk of ≤15 clips is merged with xfade, then all chunks are concat'd.
    if n > _XFADE_CHUNK_SIZE:
        result = _chunked_merge(clip_paths, output_path, transition_types, transition_duration, export)
    else:
        result = _xfade_merge(clip_paths, output_path, transition_types, transition_duration, export)

    # A chained xfade can silently drop the video tail (audio keeps going, so the
    # picture freezes for minutes). Never hand over a film whose picture is
    # shorter than its sound: hard-cut concat instead — the timeline stays exact.
    ok, video, audio = _merge_is_sound(result)
    if not ok:
        log.warning(
            f"  xfade produced a shorter picture than sound ({video:.1f}s video vs "
            f"{audio:.1f}s audio) — re-merging with hard cuts so nothing freezes."
        )
        return _fallback_concat(clip_paths, output_path, export)
    return result


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

    # Frame-rate normalisation is MANDATORY. A scene is cut to an arbitrary voice
    # length (e.g. 7.299674 s = 219 frames), so its average frame rate is not
    # exactly the export fps (29.997 here). xfade does not fail on that — it emits
    # the tail of the FIRST input only, so the chunk silently comes out seconds
    # short (measured: 7.30 s for 15.30 s of input) and the picture freezes under
    # the narration. Forcing CFR + quantising every duration to whole frames makes
    # the xfade chain exact.
    fps = export.fps
    qdur = [round(d * fps) / fps for d in durations]

    filter_parts = []
    audio_parts = []
    cumulative_dur = 0.0
    offsets = []
    for i in range(n - 1):
        cumulative_dur += qdur[i]
        offsets.append(max(cumulative_dur - transition_duration * (i + 1), 0))

    for i in range(n):
        filter_parts.append(f"[{i}:v]setsar=1[vn{i}]")

    if n == 2:
        xfade_name = _XFADE_MAP.get(transition_types[0], "fade")
        filter_parts.append(
            f"[vn0][vn1]xfade=transition={xfade_name}:duration={transition_duration}"
            f":offset={offsets[0]:.6f}[vout]"
        )
    else:
        prev_v = "[vn0]"
        for i in range(n - 1):
            xfade_name = _XFADE_MAP.get(transition_types[i], "fade")
            next_v = f"[v{i}]" if i < n - 2 else "[vout]"
            filter_parts.append(
                f"{prev_v}[vn{i + 1}]xfade=transition={xfade_name}"
                f":duration={transition_duration}:offset={offsets[i]:.6f}{next_v}"
            )
            prev_v = next_v

    # AUDIO — never crossfade the narration. Every scene's audio is padded to
    # voice + gap + transition_duration, so the outgoing clip's last
    # transition_duration seconds are SILENCE. An acrossfade therefore multiplied
    # the NEXT line's opening by a fade-in curve: measured on a real render, the
    # first 100 ms of the incoming line sat at -15 dB and only reached full level
    # after ~0.5 s — every line sounded swallowed at the cut.
    #
    # Trimming the silence and concatenating keeps the words untouched and the
    # total length equal to the xfaded picture. It is done in three steps because
    # a multi-input `concat` FILTER deadlocks against the xfade chain (ffmpeg
    # stalls until the 30-minute timeout and the chunk silently degrades to hard
    # cuts): (1) xfade the picture alone, (2) trim each clip's silent tail and
    # join the parts with the concat DEMUXER, (3) mux the two streams together.
    filter_complex = ";".join(filter_parts)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import shutil

    tmp_dir = output_path.parent / f"_xf_{output_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_video = tmp_dir / "video.mp4"
    tmp_audio = tmp_dir / "audio.wav"

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def _run(cmd: list, description: str, timeout: int) -> None:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{description} failed: {result.stderr[-600:]}")

    try:
        # 1. picture: the xfade chain, no audio at all
        _run(
            [ffmpeg, "-y", "-hide_banner", *inputs,
             "-filter_complex", filter_complex, "-map", "[vout]", "-an",
             *_video_flags(export), "-pix_fmt", export.pixel_format, str(tmp_video)],
            "video xfade", 1800,
        )

        # 2. narration: each clip minus its (silent) overlap tail, then joined
        parts = []
        for i, p in enumerate(clip_paths):
            end = max(0.01, qdur[i] - (transition_duration if i < n - 1 else 0.0))
            part = tmp_dir / f"a{i:03d}.wav"
            _run(
                [ffmpeg, "-y", "-hide_banner", "-i", str(p), "-vn",
                 "-af", "aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo",
                 "-t", f"{end:.3f}", "-c:a", "pcm_s16le", str(part)],
                f"audio part {i + 1}", 300,
            )
            parts.append(part)

        list_file = tmp_dir / "parts.txt"
        list_file.write_text(
            "".join(f"file '{q.as_posix()}'\n" for q in parts), encoding="utf-8"
        )
        _run(
            [ffmpeg, "-y", "-hide_banner", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c:a", "pcm_s16le", str(tmp_audio)],
            "audio concat", 900,
        )

        # 3. put the picture and the narration back together (no re-encode)
        _run(
            [ffmpeg, "-y", "-hide_banner", "-i", str(tmp_video), "-i", str(tmp_audio),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", export.audio_codec, "-b:a", export.audio_bitrate,
             "-ar", "44100", "-ac", "2", str(output_path)],
            "mux", 900,
        )

        # 4. xfade on this ffmpeg build silently truncates any input that carries
        #    B-frames (measured: 8.5s + 8.5s merged to 8.5s of picture). Scenes
        #    rendered before the "-bf 0" flag existed still have them, so rebuild
        #    the chunk from B-frame-free copies and fade again before falling back
        #    to hard cuts.
        ok, v_dur, a_dur = _merge_is_sound(output_path, tolerance=0.25)
        if not ok:
            log.warning(
                f"  xfade left {v_dur:.1f}s of picture for {a_dur:.1f}s of sound — "
                f"retrying these {n} clips without B-frames."
            )
            norm_inputs = []
            for i, p in enumerate(clip_paths):
                nb = tmp_dir / f"nb_{i:02d}.mp4"
                _run(
                    [ffmpeg, "-y", "-hide_banner", "-i", str(p), "-an",
                     *_video_flags(export), "-bf", "0",
                     "-pix_fmt", export.pixel_format, str(nb)],
                    f"strip B-frames {i + 1}", 900,
                )
                norm_inputs.extend(["-i", str(nb)])
            _run(
                [ffmpeg, "-y", "-hide_banner", *norm_inputs,
                 "-filter_complex", filter_complex, "-map", "[vout]", "-an",
                 *_video_flags(export), "-bf", "0",
                 "-pix_fmt", export.pixel_format, str(tmp_video)],
                "video xfade (no B-frames)", 1800,
            )
            _run(
                [ffmpeg, "-y", "-hide_banner", "-i", str(tmp_video), "-i", str(tmp_audio),
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                 "-c:a", export.audio_codec, "-b:a", export.audio_bitrate,
                 "-ar", "44100", "-ac", "2", str(output_path)],
                "mux (no B-frames)", 900,
            )
            ok, v_dur, a_dur = _merge_is_sound(output_path, tolerance=0.25)
            if not ok:
                log.warning(
                    f"  still short after stripping B-frames ({v_dur:.1f}s picture / "
                    f"{a_dur:.1f}s sound) — hard cuts for this chunk."
                )
                return _fallback_concat(clip_paths, output_path, export)

        log.info(f"  xfade merged {n} clips → {output_path.name}")
        return output_path
    except subprocess.TimeoutExpired:
        log.warning(f"xfade timed out for {n} clips, falling back to concat.")
        return _fallback_concat(clip_paths, output_path, export)
    except Exception as exc:
        log.warning(f"xfade merge failed ({exc}), falling back to concat.")
        return _fallback_concat(clip_paths, output_path, export)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
            # A bad xfade chunk keeps its audio but loses the tail of its picture,
            # which plays as a long frozen frame. Verify and rebuild that chunk
            # with hard cuts instead of shipping the freeze.
            ok, v_dur, a_dur = _merge_is_sound(chunk_out)
            if not ok:
                log.warning(
                    f"  Chunk {chunk_num + 1}: xfade left {v_dur:.1f}s of picture for "
                    f"{a_dur:.1f}s of sound — rebuilding this chunk with hard cuts."
                )
                _fallback_concat(chunk_clips, chunk_out, export)

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

