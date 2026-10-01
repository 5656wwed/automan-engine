"""Scene renderer — generates individual scene clips (image + voice → MP4)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from pathlib import Path
from typing import Callable, Optional

from app.core.config import ExportSettings, MotionType, get_config
from app.core.project import Project, SceneConfig, OverlayItem
from app.ffmpeg.wrapper import (image_to_video, add_audio_to_video, mp4_to_clip,
                                concatenate_videos)
from app.renderer.motion import get_motion_filter, resolve_scene_motion
from app.tts.voice_manager import VoiceManager
from app.utils.audio import get_audio_duration, add_silence_padding
from app.utils.logger import get_logger


# Motion for shot 1, 2, 3 … of a split still beat. Shot 1 keeps the scene's own
# Ken Burns move; every later shot alternates WIDE (normal framing, 1.0–1.08)
# with a TIGHT punch-in that starts at 1.30 — the framing jump is what makes the
# mid-beat change read as a new shot instead of one continuous drift.
_WIDE_FOR = {
    MotionType.ZOOM_IN: MotionType.PAN_RIGHT,
    MotionType.ZOOM_OUT: MotionType.PAN_LEFT,
    MotionType.ZOOM_IN_LEFT: MotionType.PAN_RIGHT,
    MotionType.ZOOM_IN_RIGHT: MotionType.PAN_LEFT,
    MotionType.ZOOM_OUT_LEFT: MotionType.PAN_RIGHT,
    MotionType.ZOOM_OUT_RIGHT: MotionType.PAN_LEFT,
    MotionType.PAN_LEFT: MotionType.ZOOM_IN,
    MotionType.PAN_RIGHT: MotionType.ZOOM_IN,
    MotionType.CAMERA_DRIFT: MotionType.ZOOM_IN,
    MotionType.NONE: MotionType.ZOOM_IN,
}


def _alternate_motion(base_motion, index: int) -> MotionType:
    """Pick the motion for shot `index` of a split still beat."""
    try:
        base = base_motion if isinstance(base_motion, MotionType) else MotionType(str(base_motion))
    except ValueError:
        base = MotionType.ZOOM_IN
    if index == 0:
        return base
    if index % 2 == 1:
        return MotionType.CUT_IN          # tight punch-in → visible cut
    return _WIDE_FOR.get(base, MotionType.ZOOM_IN)   # back out to a wide shot


def _scene_cache_key(
    provider: Optional[str],
    voice_id: Optional[str],
    script: str,
    tts_kwargs: dict,
    image_path: str,
    motion_type: str,
    export_res: str,
    overlay_text=None,
    subtitles_enabled: bool = False,
    subtitles_style: str = "auto",
    font_path: Optional[str] = None,
    color_filter: Optional[str] = None,
    music_cfg: Optional[str] = None,
    timing: str = "",
) -> str:
    if isinstance(overlay_text, list):
        overlay_str = "||".join(f"{o.text}:{o.trigger}" for o in overlay_text)
    else:
        overlay_str = overlay_text or ""
    parts = [
        "sub_v4",
        provider or "",
        voice_id or "",
        script or "",
        repr(sorted(tts_kwargs.items())),
        str(Path(image_path).name),
        motion_type,
        export_res,
        overlay_str,
        str(subtitles_enabled),
        subtitles_style,
        font_path or "",
        color_filter or "",
        music_cfg or "",
        # Pace settings change the length of the clip itself — a cached clip
        # rendered with a different padding/cut must not be reused.
        timing or "",
    ]
    # Re-render when the pronunciation dictionary changes.
    from app.tts.pronunciation import pronunciation_version
    parts.append(pronunciation_version())
    digest = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


# ---------------------------------------------------------------------------
# Overlay helpers
# ---------------------------------------------------------------------------
def _find_font(project_dir: Path) -> Optional[Path]:
    """Locate the overlay font file in the project directory."""
    for candidate in [
        project_dir / "font" / "Tox Typewriter.ttf",
        project_dir / "fonts" / "Tox Typewriter.ttf",
    ]:
        if candidate.exists():
            return candidate
    for folder in ["font", "fonts"]:
        d = project_dir / folder
        if d.exists():
            ttfs = sorted(d.glob("*.ttf"))
            if ttfs:
                return ttfs[0]
    return None


def _find_sfx(project_dir: Path) -> Optional[Path]:
    """Locate the overlay SFX file in the project directory."""
    sfx = project_dir / "sfx" / "whoosh.mp3"
    return sfx if sfx.exists() else None


def _find_overlay_start(timestamp_info: Optional[dict], overlay_text: str) -> float:
    """Find when the first word of overlay_text is spoken. Returns seconds."""
    if not timestamp_info:
        return 0.3
    wa = timestamp_info.get("wordAlignment", {})
    words  = wa.get("words", [])
    starts = wa.get("wordStartTimeSeconds", [])
    if not words or not starts:
        return 0.3
    real   = [(w, t) for w, t in zip(words, starts) if w.strip()]
    target = overlay_text.split()[0].lower().rstrip(".,!?;:")
    for word, t in real:
        if word.lower().rstrip(".,!?;:") == target:
            return t
    for word, t in real:
        if target in word.lower():
            return t
    return 0.3


def _find_overlay_start_after(timestamp_info: Optional[dict], overlay_text: str, after_time: float = 0.0) -> float:
    """Find when the first word of overlay_text is spoken, after after_time."""
    if not timestamp_info:
        return max(0.3, after_time + 0.5)
    wa = timestamp_info.get("wordAlignment", {})
    words  = wa.get("words", [])
    starts = wa.get("wordStartTimeSeconds", [])
    if not words or not starts:
        return max(0.3, after_time + 0.5)
    
    real = [(w, t) for w, t in zip(words, starts) if w.strip()]
    target = overlay_text.split()[0].lower().rstrip(".,!?;:")
    
    # Try exact match first, filtering for times after after_time
    for word, t in real:
        if t >= after_time and word.lower().rstrip(".,!?;:") == target:
            return t
            
    # Try partial match, filtering for times after after_time
    for word, t in real:
        if t >= after_time and target in word.lower():
            return t
            
    # Fallback to absolute match anywhere if not found after after_time
    for word, t in real:
        if word.lower().rstrip(".,!?;:") == target:
            return t
            
    return max(0.3, after_time + 0.5)


def _escape_drawtext_text(text: str) -> str:
    """Escape text for FFmpeg drawtext text= option.

    Wraps the entire value in a single pair of single-quotes.
    Inside the single-quoted region, only \\, \\', and \\: need escaping.
    Unicode dashes are normalised to ASCII hyphen first to avoid multi-byte
    corruption on Windows.
    """
    text = (text
            .replace('–', '-')
            .replace('—', '-')
            .replace('−', '-'))
    text = text.replace('\\', '\\\\')
    text = text.replace("'", "'\\''")
    text = text.replace(':', '\\:')
    return f"'{text}'"



def _build_drawtext_filters(
    overlay_text: str,
    overlay_start: float,
    font_path: str,
    font_size: int,
    type_duration: float,
    vanish_delay: float = 1.0,
) -> list[str]:
    """Build a typewriter drawtext filter chain for FFmpeg -vf."""
    font_ffmpeg = font_path.replace("\\", "/").replace(":", "\\:")
    char_delay  = type_duration / max(len(overlay_text), 1)
    text_end    = overlay_start + type_duration
    vanish_at   = text_end + vanish_delay
    filters     = []
    for i in range(len(overlay_text)):
        t0      = overlay_start + i * char_delay
        t1      = overlay_start + (i + 1) * char_delay
        partial = overlay_text[:i + 1]
        partial_escaped = _escape_drawtext_text(partial)
        enable  = (
            f"between(t,{t0:.3f},{t1:.3f})"
            if i < len(overlay_text) - 1
            else f"between(t,{t0:.3f},{vanish_at:.3f})"
        )
        filters.append(
            f"drawtext=fontfile='{font_ffmpeg}'"
            f":text={partial_escaped}"
            f":fontsize={font_size}"
            f":fontcolor=white"
            f":x=80:y=(h-{font_size})/2"
            f":enable='{enable}'"
            f":shadowcolor=black@0.9:shadowx=4:shadowy=4"
        )
    return filters


def _build_sequential_drawtext_filters(
    overlay_items: list,
    trigger_times: list[float],
    font_path: str,
    font_size: int,
    type_duration: float,
    vanish_delay: float = 1.0,
) -> list[str]:
    """Build vertical stacked drawtext typewriter filters for a list of items."""
    font_ffmpeg = font_path.replace("\\", "/").replace(":", "\\:")
    N = len(overlay_items)
    if N == 0:
        return []
        
    # Scale font size down slightly for longer lists to ensure they fit in 1080p height
    if N > 2:
        scale_factor = 0.8 if N <= 4 else 0.6
        font_size = max(45, int(font_size * scale_factor))

    # Spacing and positioning calculations
    # Vertically center the entire block of text.
    line_height = font_size
    line_spacing = int(font_size * 0.3)  # space between lines
    total_block_height = N * line_height + (N - 1) * line_spacing
    
    # y-coordinate of the first line
    y_start_expr = f"(h-{total_block_height})/2"
    
    # All items vanish together at the end of the scene
    last_item_end = max(trigger_times) + type_duration
    vanish_at = last_item_end + vanish_delay
    
    filters = []
    for idx, (item, t_start) in enumerate(zip(overlay_items, trigger_times)):
        # Format the item with a bullet if it doesn't have one
        text = item.text.strip()
        if not any(text.startswith(b) for b in ("•", "-", "*", "• ")):
            text = f"• {text}"
            
        # Character delay for typewriter effect on this line
        char_delay = type_duration / max(len(text), 1)
        
        # Calculate y position for this specific line
        y_pos_expr = f"{y_start_expr}+{idx * (line_height + line_spacing)}"
        
        for i in range(len(text)):
            t0 = t_start + i * char_delay
            t1 = t_start + (i + 1) * char_delay
            partial = text[:i + 1]
            partial_escaped = _escape_drawtext_text(partial)
            
            # For each character step, enable it
            # If it's the last character of the line, it stays until the entire list vanishes
            enable = (
                f"between(t,{t0:.3f},{t1:.3f})"
                if i < len(text) - 1
                else f"between(t,{t0:.3f},{vanish_at:.3f})"
            )
            
            filters.append(
                f"drawtext=fontfile='{font_ffmpeg}'"
                f":text={partial_escaped}"
                f":fontsize={font_size}"
                f":fontcolor=white"
                f":x=120"  # Indent list items
                f":y={y_pos_expr}"
                f":enable='{enable}'"
                f":shadowcolor=black@0.9:shadowx=4:shadowy=4"
            )
    return filters


def _find_subtitle_font(project_dir: Path, font_path: Optional[Path] = None) -> Path | str:
    """Locate the project font or fallback to a standard system font."""
    if font_path:
        return font_path
    proj_font = _find_font(project_dir)
    if proj_font:
        return proj_font
    
    # Fallback paths for Windows
    import sys
    if sys.platform == "win32":
        for font_name in ["trebucbd.ttf", "arialbd.ttf", "segoeuib.ttf", "tahomabd.ttf"]:
            p = Path("C:/Windows/Fonts") / font_name
            if p.exists():
                return p
    return "Arial"  # FFmpeg might fall back to its internal or system default font


def _estimate_word_timestamps(script: str, duration: float) -> dict:
    """Estimate word timestamps based on script text and audio duration."""
    words = script.strip().split()
    if not words:
        return {"wordAlignment": {"words": [], "wordStartTimeSeconds": []}}
    
    # Estimate timing: distribute active speaking duration proportionally by word character length
    word_lens = [len(w) for w in words]
    total_len = sum(word_lens) if word_lens else 1
    
    # Heuristic: average speech rate is ~150 words per minute (0.4s per word).
    # Active speaking duration is usually shorter than the total file duration because of trailing silence.
    avg_word_dur = 0.36  # seconds per word
    active_duration = min(duration - 0.3, len(words) * avg_word_dur)
    active_duration = max(0.5, active_duration)
    
    starts = []
    current_time = 0.1 # start slightly in
    
    for length in word_lens:
        starts.append(current_time)
        word_duration = (length / total_len) * active_duration
        current_time += word_duration
        
    return {
        "wordAlignment": {
            "words": words,
            "wordStartTimeSeconds": starts
        }
    }


def _build_subtitle_filters(
    script: str,
    timestamp_info: Optional[dict],
    aspect_ratio: str,
    font_path: str | Path,
    width: int,
    height: int,
    speech_duration: float,
    style: str = "auto",
) -> list[str]:
    """Build subtitle drawtext filters for word-by-word or normal line mode."""
    if not script.strip():
        return []

    # Parse timestamps
    timestamp_info = timestamp_info or {}
    wa = timestamp_info.get("wordAlignment", {})
    words = wa.get("words", [])
    starts = wa.get("wordStartTimeSeconds", [])

    # Filter out empty entries
    real_words = []
    real_starts = []
    for w, t in zip(words, starts):
        w_stripped = w.strip()
        if w_stripped:
            real_words.append(w_stripped)
            real_starts.append(t)

    if not real_words:
        return []

    # Resolve style
    resolved_style = style
    if style == "auto":
        resolved_style = "word_by_word" if aspect_ratio == "9:16" else "normal"

    font_ffmpeg = str(font_path).replace("\\", "/").replace(":", "\\:")
    filters = []

    if resolved_style == "word_by_word":
        # Centered bold word-by-word (Hormozi style)
        # Font size scales with width (8% of width, typical for portrait layout)
        font_size = max(50, int(width * 0.08))
        
        for i, word in enumerate(real_words):
            t_start = real_starts[i]
            t_end = real_starts[i+1] if i + 1 < len(real_starts) else speech_duration
            
            # Avoid lingering on the last word or in silent gaps
            t_end = min(t_end, t_start + 1.0)
            
            if t_start >= speech_duration:
                break

            # Format: uppercase, clean punctuation
            word_clean = word.upper().strip(".,!?;:\"'()[]{}")
            if not word_clean:
                continue

            partial_escaped = _escape_drawtext_text(word_clean)
            enable = f"between(t,{t_start:.3f},{t_end:.3f})"
            
            # Draw single active word at y=h*0.6
            filters.append(
                f"drawtext=fontfile='{font_ffmpeg}'"
                f":text={partial_escaped}"
                f":fontsize={font_size}"
                f":fontcolor=yellow"
                f":x=(w-text_w)/2"
                f":y=h*0.6"
                f":borderw=4:bordercolor=black"
                f":enable='{enable}'"
            )
    else:
        # Standard line-by-line subtitles
        # Font size scales with width (2.5% of width)
        font_size = max(28, int(width * 0.025))
        
        # Group words into phrases (max 6 words or pause or punctuation)
        phrases = []
        current_words = []
        current_start = None
        
        for idx, word in enumerate(real_words):
            t_start = real_starts[idx]
            if current_start is None:
                current_start = t_start
                
            current_words.append(word)
            
            end_phrase = False
            if len(current_words) >= 6:
                end_phrase = True
            elif word[-1] in ('.', '?', '!', ',', ';', ':'):
                end_phrase = True
            elif idx + 1 < len(real_starts) and real_starts[idx+1] - t_start > 1.2:
                end_phrase = True
                
            if end_phrase or idx == len(real_words) - 1:
                t_end = real_starts[idx+1] if idx + 1 < len(real_starts) else speech_duration
                if t_end - current_start > 3.0:
                    t_end = current_start + 2.5
                    
                text = " ".join(current_words).strip()
                if text:
                    phrases.append({
                        "text": text,
                        "start": current_start,
                        "end": t_end
                    })
                current_words = []
                current_start = None

        for phrase in phrases:
            if phrase["start"] >= speech_duration:
                continue
            partial_escaped = _escape_drawtext_text(phrase["text"])
            enable = f"between(t,{phrase['start']:.3f},{phrase['end']:.3f})"
            
            # Bottom centered subtitles at y=h*0.82
            filters.append(
                f"drawtext=fontfile='{font_ffmpeg}'"
                f":text={partial_escaped}"
                f":fontsize={font_size}"
                f":fontcolor=white"
                f":x=(w-text_w)/2"
                f":y=h*0.82"
                f":borderw=3:bordercolor=black"
                f":enable='{enable}'"
                f":shadowcolor=black@0.6:shadowx=2:shadowy=2"
            )
            
    return filters


log = get_logger("renderer.scene")


class SceneRenderer:
    """Renders individual scenes: TTS → audio, image + audio → video clip."""

    def __init__(
        self,
        project: Project,
        voice_manager: VoiceManager,
        export: Optional[ExportSettings] = None,
    ):
        self.project = project
        self.voice_manager = voice_manager
        self.export = export or ExportSettings(
            resolution=project.config.resolution,
            fps=project.config.fps,
        )
        import hashlib
        project_hash = hashlib.md5(str(project.project_dir.resolve()).encode()).hexdigest()[:10]
        self._work_dir = project.project_output_dir / ".tmp" / project_hash
        self._work_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_font_path(self) -> Optional[Path]:
        """Resolve the font path to use based on project and global settings."""
        font_path = None
        if getattr(self.project.config, "font_path", None):
            p = Path(self.project.config.font_path)
            if p.is_absolute() and p.exists():
                font_path = p
            elif (self.project.project_dir / p).exists():
                font_path = self.project.project_dir / p
            else:
                log.warning(f"Project font_path '{self.project.config.font_path}' was set but not found on disk.")

        if not font_path and get_config().overlay_font_path:
            p = Path(get_config().overlay_font_path)
            if p.exists():
                font_path = p
            else:
                log.warning(f"Global overlay_font_path '{get_config().overlay_font_path}' was set but not found on disk.")

        if not font_path:
            font_path = _find_font(self.project.project_dir)
            
        return font_path

    def _resolve_lut(self, name: str) -> Optional[Path]:
        """Resolve a .cube LUT by name from theautoman/luts/ (case-insensitive)."""
        if not name:
            return None
        luts_dir = Path(__file__).resolve().parent.parent.parent / "luts"
        if not luts_dir.exists():
            return None
        # exact or with .cube appended
        for candidate in (luts_dir / name, luts_dir / f"{name}.cube"):
            if candidate.exists():
                return candidate
        low = name.lower()
        for f in luts_dir.glob("*.cube"):
            if f.stem.lower() == low:
                return f
        return None

    def _resolve_music(self, name) -> Optional[Path]:
        """Resolve an uploaded background-music file by name (theautoman/music/)."""
        if not name:
            return None
        music_dir = Path(__file__).resolve().parent.parent.parent / "music"
        if not music_dir.exists():
            return None
        for candidate in (music_dir / str(name), music_dir / f"{name}.mp3", music_dir / f"{name}.wav"):
            if candidate.exists():
                return candidate
        low = str(name).lower()
        for f in music_dir.iterdir():
            if f.is_file() and f.stem.lower() == low:
                return f
        return None

    async def render_scene(
        self,
        scene: SceneConfig,
        scene_index: int,
        progress_callback: Optional[Callable[[int, str, float], None]] = None,
    ) -> Path:
        """Render a single scene through the full pipeline.

        Args:
            scene: Scene configuration.
            scene_index: 0-based index of the scene.
            progress_callback: Optional (scene_index, stage, progress) callback.

        Returns:
            Tuple of (Path to clip, Duration in seconds).
        """
        scene_num = scene_index + 1
        prefix = f"scene_{scene_num:03d}"

        def _progress(stage: str, pct: float):
            if progress_callback:
                progress_callback(scene_index, stage, pct)

        _progress("Starting", 0.0)
        log.info(f"═══ Rendering Scene {scene_num}/{self.project.scene_count} ═══")
        log.info(f"  Image : {Path(scene.image).name}")
        log.info(f"  Script: {scene.script[:80]}{'...' if len(scene.script) > 80 else ''}")

        # ── Step 1: Generate voiceover ──────────────────────────────
        _progress("Generating voiceover", 0.1)

        # Determine provider and voice_id for this scene
        provider = None
        voice_id = None

        if scene.voice:
            provider = scene.voice.provider
            voice_id = scene.voice.voice_id
        elif scene.voice_id:
            voice_id = scene.voice_id

        if not provider and self.project.config.voice:
            provider = self.project.config.voice.provider
        if not voice_id and self.project.config.voice:
            voice_id = self.project.config.voice.voice_id

        tts_kwargs = {}
        voice_volume = 1.0
        voice_cfg = scene.voice or (self.project.config.voice if self.project.config.voice else None)
        if voice_cfg:
            if voice_cfg.speed is not None:
                tts_kwargs["speed"] = voice_cfg.speed
            if voice_cfg.pitch is not None:
                tts_kwargs["pitch"] = voice_cfg.pitch
            if voice_cfg.stability is not None:
                tts_kwargs["stability"] = voice_cfg.stability
            if voice_cfg.emotion is not None:
                tts_kwargs["emotion"] = voice_cfg.emotion
            if voice_cfg.volume is not None:
                voice_volume = voice_cfg.volume
                tts_kwargs["volume"] = voice_cfg.volume

        log.info(f"  Voice  : {provider or 'default'} / {voice_id or 'default'}")

        # Cache key now encodes voice + script + TTS params + image + motion + font
        # This allows us to RESUME renders by skipping identical clips.
        motion = resolve_scene_motion(
            scene_motion=scene.motion,
            project_motion=self.project.config.motion,
            randomize=self.project.config.randomize_motion if self.project.config.randomize_motion is not None else get_config().render.randomize_motion,
            scene_index=scene_index,
        )

        overlay_text = scene.overlay_text  # already normalized to None by validator
        font_path = self._resolve_font_path()
        font_path_str = str(font_path) if font_path else None

        cache_key = _scene_cache_key(
            provider, voice_id, scene.script, tts_kwargs,
            scene.image, motion.value, self.export.resolution,
            overlay_text,
            getattr(self.project.config, "subtitles_enabled", False),
            getattr(self.project.config, "subtitles_style", "auto") or "auto",
            font_path=font_path_str,
            color_filter=getattr(self.project.config, "color_filter", None),
            music_cfg=str((getattr(self.project.config, "music_name", None) or "")
                          + "|" + str(getattr(self.project.config, "music_volume", None) or "")
                          + "|" + str(getattr(self.project.config, "mute_original", False))
                          + "|" + str(getattr(self.project.config, "music_loop", True))),
            timing=str(getattr(self.project.config, "duration_padding", None))
                   + "|" + str(getattr(self.project.config, "picture_cut_seconds", None))
                   + "|" + str(getattr(self.project.config, "transition_duration", None))
                   + "|" + str(getattr(self.project.config, "beat_seconds", None)),
        )
        
        final_clip = self._work_dir / f"{prefix}_{cache_key}.mp4"
        
        # --- RESUME LOGIC ---
        if final_clip.exists():
            try:
                duration = get_audio_duration(final_clip)
                log.info(f"  ✓ Skipping Scene {scene_num} (already rendered: {final_clip.name})")
                _progress("Complete (Skipped)", 1.0)
                return final_clip, duration
            except Exception as e:
                log.warning(f"  ⚠ Existing clip {final_clip.name} is corrupt or incomplete: {e}. Re-rendering.")
                try:
                    final_clip.unlink(missing_ok=True)
                except Exception:
                    pass

        audio_path = self._work_dir / f"{prefix}_{cache_key}_voice.mp3"
        timestamps_path = self._work_dir / f"{prefix}_{cache_key}_voice.json"

        want_timestamps = (overlay_text is not None) or getattr(self.project.config, "subtitles_enabled", False)

        if audio_path.exists() and (not want_timestamps or timestamps_path.exists()) and get_config().render.cache_audio:
            tts_result_duration = get_audio_duration(audio_path)
            if timestamps_path.exists():
                try:
                    import json
                    with open(timestamps_path, "r", encoding="utf-8") as f:
                        tts_word_timestamps = json.load(f)
                except Exception:
                    tts_word_timestamps = None
            else:
                tts_word_timestamps = None
        else:
            tts_result = await self.voice_manager.generate(
                text=scene.script,
                output_path=audio_path,
                provider=provider,
                voice_id=voice_id,
                want_timestamps=want_timestamps,
                **tts_kwargs,
            )
            tts_result_duration = tts_result.duration
            tts_word_timestamps = tts_result.word_timestamps
            if tts_word_timestamps:
                try:
                    import json
                    with open(timestamps_path, "w", encoding="utf-8") as f:
                        json.dump(tts_word_timestamps, f, indent=2)
                except Exception as e:
                    log.warning(f"  ⚠ Failed to cache word timestamps: {e}")
            # Brief pause between TTS API calls to avoid rate limiting
            await asyncio.sleep(2)

        _progress("Voiceover complete", 0.4)

        # ── Step 2: Calculate scene duration ─────────────────────────
        padding = scene.duration_padding
        if padding is None:
            padding = self.project.config.duration_padding
        if padding is None:
            padding = get_config().render.duration_padding
        if padding is None:
            padding = 0.5

        t_dur = self.project.config.transition_duration
        if t_dur is None:
            t_dur = get_config().render.transition_duration
        if t_dur is None:
            t_dur = 0.5

        target_duration = tts_result_duration + padding + t_dur

        # BEAT LENGTH — the pipeline's unit is an 8-second beat (60 beats = 8:00).
        # When beat_seconds is set, every beat's picture is exactly that long:
        # a short narration line holds its shot for the rest of the beat, and a
        # line longer than the beat is never cut (the voice always wins).
        beat_target = scene.beat_seconds
        if beat_target is None:
            beat_target = getattr(self.project.config, "beat_seconds", None)
        if beat_target is None:
            beat_target = get_config().render.beat_seconds
        if beat_target and beat_target > 0:
            if target_duration < beat_target + t_dur:
                target_duration = beat_target + t_dur
            log.info(f"  Beat length: {beat_target:.2f}s "
                     f"(voice {tts_result_duration:.2f}s)")

        if overlay_text:
            cfg = get_config()
            type_duration = cfg.overlay_type_duration
            vanish_delay = 1.0
            if isinstance(overlay_text, list):
                trigger_times = []
                last_start = 0.0
                for item in overlay_text:
                    start = _find_overlay_start_after(tts_word_timestamps, item.trigger, last_start)
                    trigger_times.append(start)
                    last_start = start
                last_overlay_end = max(trigger_times) + type_duration + vanish_delay if trigger_times else 0.3
            else:
                last_overlay_end = _find_overlay_start(tts_word_timestamps, overlay_text) + type_duration + vanish_delay
            required_for_overlay = last_overlay_end + t_dur
            if target_duration < required_for_overlay:
                target_duration = required_for_overlay
                log.info(f"  Extended scene duration to {target_duration:.1f}s to allow overlay to finish.")

        padded_audio = self._work_dir / f"{prefix}_{cache_key}_voice_padded.mp3"
        needed_padding = max(0.0, target_duration - tts_result_duration)
        add_silence_padding(audio_path, padded_audio, padding_seconds=needed_padding, position="end")
        scene_duration = get_audio_duration(padded_audio)

        log.info(f"  Duration: {tts_result_duration:.1f}s voice + {needed_padding:.1f}s padding = {scene_duration:.1f}s")

        # ── Step 3: Render video (image → Ken Burns, or MP4 → scale/trim) ──
        _progress("Rendering video", 0.5)
        raw_video = self._work_dir / f"{prefix}_raw.mp4"

        is_mp4 = Path(scene.image).suffix.lower() == ".mp4"

        motion_filter = get_motion_filter(
            motion=motion,
            width=self.export.width,
            height=self.export.height,
            duration=scene_duration,
            fps=self.export.fps,
        )

        if is_mp4:
            log.info(f"  Source : MP4 video — trimmed to {scene_duration:.1f}s, Ken Burns skipped")
        else:
            log.info(f"  Motion : {motion.value}")

        # Resolve overlay assets
        overlay_filters = []
        sfx_path        = None
        sfx_delay_ms    = 0

        if overlay_text:
            if font_path:
                cfg = get_config()
                if isinstance(overlay_text, list):
                    trigger_times = []
                    last_start = 0.0
                    for item in overlay_text:
                        start = _find_overlay_start_after(tts_word_timestamps, item.trigger, last_start)
                        trigger_times.append(start)
                        last_start = start
                    overlay_filters.extend(_build_sequential_drawtext_filters(
                        overlay_text, trigger_times,
                        str(font_path), cfg.overlay_font_size, cfg.overlay_type_duration,
                    ))
                    overlay_start = trigger_times[0] if trigger_times else 0.3
                    log.info(f"  Overlay list: {len(overlay_text)} items, first at {overlay_start:.3f}s")
                else:
                    overlay_start = _find_overlay_start(tts_word_timestamps, overlay_text)
                    overlay_filters.extend(_build_drawtext_filters(
                        overlay_text, overlay_start,
                        str(font_path), cfg.overlay_font_size, cfg.overlay_type_duration,
                    ))
                    log.info(f"  Overlay: '{overlay_text}' at {overlay_start:.3f}s")
                sfx_path     = _find_sfx(self.project.project_dir)
                sfx_delay_ms = int(overlay_start * 1000)
            else:
                log.warning("  Overlay skipped: font file not found in project/font/")

        if getattr(self.project.config, "subtitles_enabled", False) and scene.script:
            sub_font = _find_subtitle_font(self.project.project_dir, font_path=font_path)
            timestamps_to_use = tts_word_timestamps
            if not timestamps_to_use:
                timestamps_to_use = _estimate_word_timestamps(scene.script, tts_result_duration)
            sub_filters = _build_subtitle_filters(
                script=scene.script,
                timestamp_info=timestamps_to_use,
                aspect_ratio=self.project.config.aspect_ratio or "16:9",
                font_path=sub_font,
                width=self.export.width,
                height=self.export.height,
                speech_duration=tts_result_duration,
                style=getattr(self.project.config, "subtitles_style", "auto") or "auto"
            )
            overlay_filters.extend(sub_filters)

        overlay_filters = overlay_filters if overlay_filters else None

        # CapCut-style 3D LUT + adjustment color grading (every scene)
        from app.ffmpeg.color_filter import build_color_chain
        pc = self.project.config
        color_chain = build_color_chain(
            getattr(pc, "color_filter", None),
            intensity=getattr(pc, "filter_intensity", None),
            brightness=getattr(pc, "brightness", None),
            contrast=getattr(pc, "contrast", None),
            saturation=getattr(pc, "saturation", None),
            warmth=getattr(pc, "warmth", None),
        )
        if color_chain:
            overlay_filters = list(overlay_filters or []) + [color_chain]
            log.info(f"  Color grade: {color_chain}")

        loop = asyncio.get_event_loop()
        if is_mp4:
            await loop.run_in_executor(
                None,
                lambda: mp4_to_clip(
                    video_path=scene.image,
                    output_path=raw_video,
                    duration=scene_duration,
                    export=self.export,
                    overlay_filters=overlay_filters,
                ),
            )
        else:
            # PACING — a still [IMAGE] beat held for its whole narration line
            # reads as a freeze-frame. When picture_cut_seconds is set the still
            # is broken into N shots with alternating motion (the pipeline's
            # Image A / Image B rule), so the picture changes mid-beat while the
            # voice keeps running uninterrupted over the whole beat.
            cut = getattr(self.project.config, "picture_cut_seconds", None)
            if cut is None:
                cut = get_config().render.picture_cut_seconds
            can_split = bool(
                cut and cut >= 1.0 and scene_duration >= cut * 1.5
                and not overlay_filters
                and not getattr(self.project.config, "subtitles_enabled", False)
            )
            if can_split:
                shots = max(2, min(4, int(round(scene_duration / cut))))
                per_shot = scene_duration / shots
                part_paths = []
                for k in range(shots):
                    part_motion = _alternate_motion(motion, k)
                    pf = get_motion_filter(
                        motion=part_motion,
                        width=self.export.width,
                        height=self.export.height,
                        duration=per_shot,
                        fps=self.export.fps,
                    )
                    part = self._work_dir / f"{prefix}_{cache_key}_shot{k}.mp4"
                    await loop.run_in_executor(
                        None,
                        lambda p=part, f=pf: image_to_video(
                            image_path=scene.image,
                            output_path=p,
                            duration=per_shot,
                            motion_filter=f,
                            export=self.export,
                        ),
                    )
                    part_paths.append(str(part))
                await loop.run_in_executor(
                    None,
                    lambda: concatenate_videos(part_paths, str(raw_video), self.export),
                )
                for p in part_paths:
                    with contextlib.suppress(Exception):
                        Path(p).unlink()
                log.info(f"  Picture: {shots} shots × {per_shot:.2f}s "
                         f"(new shot every {cut:.1f}s)")
            else:
                await loop.run_in_executor(
                    None,
                    lambda: image_to_video(
                        image_path=scene.image,
                        output_path=raw_video,
                        duration=scene_duration,
                        motion_filter=motion_filter,
                        export=self.export,
                        overlay_filters=overlay_filters,
                    ),
                )

        _progress("Adding audio", 0.8)

        # ── Step 4: Overlay audio onto video ─────────────────────────
        _sfx      = sfx_path
        _delay    = sfx_delay_ms
        _vol      = get_config().overlay_sfx_volume if overlay_text else 0.55
        _bg_audio = Path(scene.image) if is_mp4 else None
        _bg_vol   = get_config().mp4_bg_volume
        _voice_vol = voice_volume
        # background music + mute original
        pc = self.project.config
        _music_path = self._resolve_music(getattr(pc, "music_name", None))
        _music_vol  = getattr(pc, "music_volume", None) or 0.3
        _mute_bg    = bool(getattr(pc, "mute_original", False))
        _music_loop = bool(getattr(pc, "music_loop", True))
        await loop.run_in_executor(
            None,
            lambda: add_audio_to_video(
                video_path=raw_video,
                audio_path=padded_audio,
                output_path=final_clip,
                export=self.export,
                sfx_path=_sfx,
                sfx_delay_ms=_delay,
                sfx_volume=_vol,
                duration=scene_duration,
                bg_audio_path=_bg_audio,
                bg_audio_volume=_bg_vol,
                voice_volume=_voice_vol,
                music_path=_music_path,
                music_volume=_music_vol,
                mute_bg=_mute_bg,
                music_loop=_music_loop,
            ),
        )

        # Clean up intermediate files
        if raw_video.exists():
            raw_video.unlink()

        _progress("Complete", 1.0)
        log.info(f"  ✓ Scene {scene_num} rendered: {final_clip.name}")

        return final_clip, scene_duration

    async def render_all_scenes(
        self,
        progress_callback: Optional[Callable[[int, str, float], None]] = None,
    ) -> list[tuple[Path, float]]:
        """Render all scenes sequentially. Returns list of (clip_path, duration) tuples."""
        clips = []
        valid_clips = {}

        # 1. Pre-scan for existing valid clips to report an elegant resume status
        log.info("Checking for previously rendered scenes...")
        for i, scene in enumerate(self.project.scenes):
            # Resolve voice details
            provider = None
            voice_id = None
            if scene.voice:
                provider = scene.voice.provider
                voice_id = scene.voice.voice_id
            elif scene.voice_id:
                voice_id = scene.voice_id
            if not provider and self.project.config.voice:
                provider = self.project.config.voice.provider
            if not voice_id and self.project.config.voice:
                voice_id = self.project.config.voice.voice_id

            tts_kwargs = {}
            voice_cfg = scene.voice or (self.project.config.voice if self.project.config.voice else None)
            if voice_cfg:
                if voice_cfg.speed is not None:
                    tts_kwargs["speed"] = voice_cfg.speed
                if voice_cfg.pitch is not None:
                    tts_kwargs["pitch"] = voice_cfg.pitch
                if voice_cfg.stability is not None:
                    tts_kwargs["stability"] = voice_cfg.stability
                if voice_cfg.emotion is not None:
                    tts_kwargs["emotion"] = voice_cfg.emotion

            motion = resolve_scene_motion(
                scene_motion=scene.motion,
                project_motion=self.project.config.motion,
                randomize=self.project.config.randomize_motion if self.project.config.randomize_motion is not None else get_config().render.randomize_motion,
                scene_index=i,
            )

            font_path = self._resolve_font_path()
            font_path_str = str(font_path) if font_path else None

            cache_key = _scene_cache_key(
                provider, voice_id, scene.script, tts_kwargs,
                scene.image, motion.value, self.export.resolution,
                scene.overlay_text,
                getattr(self.project.config, "subtitles_enabled", False),
                getattr(self.project.config, "subtitles_style", "auto") or "auto",
                font_path=font_path_str,
                timing=str(getattr(self.project.config, "duration_padding", None))
                       + "|" + str(getattr(self.project.config, "picture_cut_seconds", None))
                       + "|" + str(getattr(self.project.config, "transition_duration", None))
                       + "|" + str(getattr(self.project.config, "beat_seconds", None)),
            )
            prefix = f"scene_{i + 1:03d}"
            final_clip = self._work_dir / f"{prefix}_{cache_key}.mp4"

            if final_clip.exists():
                try:
                    duration = get_audio_duration(final_clip)
                    valid_clips[i] = (final_clip, duration)
                except Exception as e:
                    log.warning(f"  ⚠ Existing clip {final_clip.name} is corrupt or incomplete: {e}. Will re-render.")
                    try:
                        final_clip.unlink(missing_ok=True)
                    except Exception:
                        pass

        skipped_count = len(valid_clips)
        if skipped_count > 0:
            log.info(f"▶ Resuming render: found {skipped_count} already rendered scenes. Resuming from Scene {skipped_count + 1}...")

        # 2. Render scenes (using valid cache or rendering fresh)
        for i, scene in enumerate(self.project.scenes):
            if i in valid_clips:
                clips.append(valid_clips[i])
                # Trigger progress update for skipped scene
                if progress_callback:
                    progress_callback(i, "Complete (Skipped)", 1.0)
            else:
                result = await self.render_scene(scene, i, progress_callback)
                clips.append(result)

        return clips

    def cleanup(self) -> None:
        """Remove temporary working directory."""
        import shutil
        if self._work_dir.exists():
            shutil.rmtree(self._work_dir, ignore_errors=True)
            log.info("Cleaned up temporary files.")
