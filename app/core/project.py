"""Project model — JSON schema definition and validation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from typing import Union
from pydantic import BaseModel, Field, field_validator

from app.core.config import MotionType, TransitionType
from app.core.exceptions import InvalidProjectError


# ---------------------------------------------------------------------------
# Scene Model
# ---------------------------------------------------------------------------
class VoiceConfig(BaseModel):
    """Voice configuration at project or scene level."""
    provider: Optional[str] = None
    voice_id: Optional[str] = None
    clone_voice: bool = False
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    pitch: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    stability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    volume: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    emotion: Optional[str] = None


class OverlayItem(BaseModel):
    """A single timed overlay: shown when trigger word is spoken by TTS."""
    text: str    # max 3 words displayed on screen
    trigger: str # single word from narration that fires this overlay


def _clean_overlay_str(s: str) -> str | None:
    import re
    s = s.strip()
    if s.lower() in ("null", "none", ""):
        return None
    s = re.sub(r"[*_~`#>]+", "", s)
    s = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s else None


class SceneConfig(BaseModel):
    """Single scene configuration."""
    title: Optional[str] = None
    image: str
    # Every picture of this beat, in order. One beat can be a run of lettered
    # images (beat-3-image-a/b/c) that together fill the beat's time; `image`
    # stays the first picture for compatibility. None/1 entry = one picture.
    images: Optional[list[str]] = None
    script: str
    overlay_text: Optional[Union[str, list[OverlayItem]]] = None
    transition: Optional[str] = None
    motion: Optional[str] = None
    duration_padding: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    # How many pictures this beat shows (>=2). None = use the project setting.
    pictures_per_beat: Optional[int] = Field(default=None, ge=0, le=12)
    # Fixed beat length in seconds (the pipeline's unit is an 8s beat). None/0 =
    # the picture follows the voice instead.
    beat_seconds: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    voice_id: Optional[str] = None
    voice: Optional[VoiceConfig] = None

    @field_validator("overlay_text", mode="before")
    @classmethod
    def normalize_overlay_text(cls, v) -> "str | list[OverlayItem] | None":
        if v is None:
            return None

        def clean_text(s: str) -> str:
            return _clean_overlay_str(s) or ""

        def parse_item(item) -> OverlayItem | None:
            if isinstance(item, dict):
                text_val = clean_text(str(item.get("text", "")))
                trigger_val = str(item.get("trigger", "")).strip().split()[0].lower() if item.get("trigger") else ""
                if text_val and trigger_val:
                    return OverlayItem(text=text_val, trigger=trigger_val)
                elif text_val:
                    t = text_val.split()[0].lower() if text_val else ""
                    if t:
                        return OverlayItem(text=text_val, trigger=t)
            else:
                text_val = clean_text(str(item))
                if text_val:
                    trigger_val = text_val.split()[0].lower()
                    return OverlayItem(text=text_val, trigger=trigger_val)
            return None

        if isinstance(v, str) and v.strip().startswith("["):
            try:
                import json
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    v = parsed
            except (json.JSONDecodeError, ValueError):
                pass

        if isinstance(v, list):
            items = []
            for item in v:
                parsed_item = parse_item(item)
                if parsed_item:
                    items.append(parsed_item)
            return items if items else None

        if isinstance(v, str):
            v_cleaned = _clean_overlay_str(v)
            if not v_cleaned:
                return None
            if ";" in v_cleaned:
                parts = v_cleaned.split(";")
                items = []
                for p in parts:
                    parsed_item = parse_item(p)
                    if parsed_item:
                        items.append(parsed_item)
                return items if items else None
            return v_cleaned

        return None

    @field_validator("transition")

    @classmethod
    def validate_transition(cls, v: str | None) -> str | None:
        if v is not None:
            valid = [t.value for t in TransitionType]
            if v.lower() not in valid:
                raise ValueError(f"Invalid transition '{v}'. Valid: {valid}")
            return v.lower()
        return v

    @field_validator("motion")
    @classmethod
    def validate_motion(cls, v: str | None) -> str | None:
        if v is not None:
            valid = [m.value for m in MotionType]
            if v.lower() not in valid:
                raise ValueError(f"Invalid motion '{v}'. Valid: {valid}")
            return v.lower()
        return v


# ---------------------------------------------------------------------------
# Project Model
# ---------------------------------------------------------------------------
class ProjectConfig(BaseModel):
    """Full project configuration from JSON file."""
    title: str = "Untitled Project"
    output: str = "final_video.mp4"
    aspect_ratio: Optional[str] = "16:9"
    resolution: str = Field(default="1920x1080", pattern=r"^\d+x\d+$")
    fps: int = Field(default=30, ge=1, le=120)
    voice: Optional[VoiceConfig] = None
    transition: Optional[str] = None
    transition_duration: Optional[float] = Field(default=None, ge=0.1, le=3.0)
    motion: Optional[str] = None
    randomize_motion: Optional[bool] = None
    duration_padding: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    # Break a still beat into shots of roughly this many seconds so the picture
    # changes mid-beat (0 / None = one held frame for the whole line).
    picture_cut_seconds: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    # Fixed beat length in seconds — 8.0 for the standard pipeline beat
    # (60 beats = 8:00). 0 / None = each picture follows its own voice.
    beat_seconds: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    # Pictures per beat (>=2) — free: 2, 3, 4 … 0 / None = use the interval.
    pictures_per_beat: Optional[int] = Field(default=None, ge=0, le=12)
    quality: Optional[str] = None
    subtitles_enabled: bool = False
    subtitles_style: str = "auto"
    font_path: Optional[str] = None
    color_filter: Optional[str] = None  # name of a .cube LUT in theautoman/luts/
    filter_intensity: Optional[float] = Field(default=None, ge=0.0, le=1.0)  # LUT blend 0-1
    brightness: Optional[float] = None   # eq brightness -1..1
    contrast: Optional[float] = None     # eq contrast 0..2 (1 neutral)
    saturation: Optional[float] = None   # eq saturation 0..3 (1 neutral)
    warmth: Optional[float] = None       # -1..1 warm/cool
    music_name: Optional[str] = None     # name of an uploaded background-music file (theautoman/music/)
    music_volume: Optional[float] = Field(default=None, ge=0.0, le=1.0)  # 0-1
    mute_original: bool = False          # drop the clip's own audio
    music_loop: bool = True              # loop the music if it's shorter than the clip
    scenes: list[SceneConfig] = Field(min_length=1)

    @field_validator("scenes")
    @classmethod
    def validate_scenes_not_empty(cls, v: list[SceneConfig]) -> list[SceneConfig]:
        if not v:
            raise ValueError("Project must contain at least one scene.")
        return v


# ---------------------------------------------------------------------------
# Project Loader
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Media kinds + discovery order
# ---------------------------------------------------------------------------
# Keep these in sync with the dashboard's ALLOWED_MEDIA (web app/main.py): a
# file the dashboard accepts must also be discovered here, or the upload is
# silently dropped and the beat ends up with no picture.
CLIP_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def is_clip_path(p: str | Path) -> bool:
    """True when a media file is a video clip (rather than a still image)."""
    return Path(p).suffix.lower() in CLIP_EXTS


def _numeric_stem(p: Path) -> int:
    """Sort key: extract the first integer from a filename stem."""
    import re as _re
    m = _re.search(r'\d+', p.stem)
    return int(m.group()) if m else 0


# ---------------------------------------------------------------------------
# Beat naming (beat-1-video-…, beat-3-image-a-…, beat-3-image-b-…)
#
# A beat is one 8-second unit of the film. Media sharing a beat number belong
# to the SAME beat: beat-3-image-a/b/c is one beat shown as three pictures, not
# three beats. A letterless "video" file is a beat on its own.
# ---------------------------------------------------------------------------
_BEAT_TOKEN_RE = re.compile(r"beat[\s._\-]*#?\s*(\d+)", re.IGNORECASE)
_BEAT_LETTER_RE = re.compile(
    r"(?:image|img|pic|picture|still|shot)[\s._\-]*([a-z])(?![a-z])", re.IGNORECASE)


def beat_number(p: str | Path) -> int | None:
    """Beat number encoded in a media filename, or None if it carries none.

    'beat-3-image-b-001.png' -> 3, 'beat-12-video-2.mp4' -> 12. Anything after
    the beat/letter part (counters, hashes) is ignored.
    """
    m = _BEAT_TOKEN_RE.search(Path(p).stem)
    return int(m.group(1)) if m else None


def beat_letter(p: str | Path) -> str:
    """Picture letter inside a beat ('beat-3-image-b-…' -> 'b'), else ''."""
    m = _BEAT_LETTER_RE.search(Path(p).stem)
    return m.group(1).lower() if m else ""


class Project:
    """Loaded project with resolved paths and validation."""

    def __init__(self, config: ProjectConfig, project_dir: Path, json_path: Path):
        self.config = config
        self.project_dir = project_dir
        self.json_path = json_path
        self._build_scene_list()

    # ------------------------------------------------------------------
    # Media discovery
    # ------------------------------------------------------------------

    def _discover_media(self) -> list[Path]:
        """Return all media files in the images/ folder (or project root).

        Order: STRICTLY by the integer in the filename stem, clips and stills
        interleaved — 01.jpg, 02.mp4, 03.jpg is discovered (and rendered) in
        exactly that order. The numbering alone therefore decides which beat
        gets a clip and which gets a still; clips are no longer hoisted to the
        front. Files with no digits sort as 0 (first) and ties break on the
        lowercase name, so the order is never random.
        `$AUTOMAN_MEDIA_ORDER=videos_first` restores the legacy order (every
        clip first, then every still).
        """
        _MEDIA_EXTS = CLIP_EXTS | IMAGE_EXTS

        search_root = self.project_dir / "images"
        if not search_root.exists():
            search_root = self.project_dir

        media = sorted(
            [f for f in search_root.iterdir()
             if f.is_file() and f.suffix.lower() in _MEDIA_EXTS],
            key=lambda p: (_numeric_stem(p), p.name.lower()),
        )

        legacy = (os.environ.get("AUTOMAN_MEDIA_ORDER", "") or "").strip().lower()
        if legacy == "videos_first":
            return ([f for f in media if is_clip_path(f)]
                    + [f for f in media if not is_clip_path(f)])
        return media

    def _group_beats(self, media: list[Path]) -> list[list[Path]]:
        """Group discovered media into beats (one beat = one 8-second unit).

        Files carrying the same `beat-N` token are ONE beat:
        `beat-3-image-a`, `beat-3-image-b`, `beat-3-image-c` render as a single
        beat whose picture time is shared between the three images — not as
        three beats. A clip inside a beat comes first, then the images by
        letter (a → b → c → d). Files with no beat token each stay their own
        beat, so plain 01.jpg / 02.mp4 projects behave exactly as before.
        """
        groups: dict[tuple, list[Path]] = {}
        for i, p in enumerate(media):
            n = beat_number(p)
            key = ("beat", n) if n is not None else ("file", i)
            groups.setdefault(key, []).append(p)

        beats: list[list[Path]] = []
        for (kind, _), paths in groups.items():
            if kind == "beat" and len(paths) > 1:
                paths = sorted(paths, key=lambda p: (0 if is_clip_path(p) else 1,
                                                     beat_letter(p),
                                                     p.name.lower()))
            beats.append(paths)
        return beats

    def _build_scene_list(self) -> None:
        """Rebuild config.scenes from the media files on disk.

        One BEAT becomes one scene. A beat is either a single file or a run of
        lettered images sharing a beat number (beat-3-image-a/b/c) — those
        pictures are attached to the scene as `images` and share its duration.
        JSON scene configs supply the script, voice, overlay, etc. positionally
        — scene config [i] is paired with beat [i]. If there are more beats
        than JSON scenes, the extra beats inherit the last scene's voice
        config and get an empty script (validation will flag those). If there
        are more JSON scenes than beats, the extra scenes are silently dropped.
        """
        all_media = self._discover_media()

        if not all_media:
            # Nothing on disk — keep JSON scenes and resolve paths normally
            self._resolve_image_paths_legacy()
            return

        beats = self._group_beats(all_media)
        multi = sum(1 for b in beats if len(b) > 1)
        if multi:
            from app.utils.logger import get_logger
            get_logger("project").info(
                f"  Beats: {len(beats)} from {len(all_media)} files "
                f"({multi} beat(s) covered by several pictures)")

        json_scenes = self.config.scenes
        new_scenes: list[SceneConfig] = []

        for i, group in enumerate(beats):
            pics = [str(p) for p in group]
            if i < len(json_scenes):
                base = json_scenes[i]
                scene = base.model_copy(update={"image": pics[0], "images": pics})
            else:
                # More beats than scripts — create a minimal scene
                template = json_scenes[-1] if json_scenes else None
                scene = SceneConfig(
                    image=pics[0],
                    images=pics,
                    script="",
                    voice=template.voice if template else None,
                )
            new_scenes.append(scene)

        self.config.scenes = new_scenes

    # ------------------------------------------------------------------
    # Legacy path resolver (used when no media folder exists on disk)
    # ------------------------------------------------------------------

    @staticmethod
    def _find_image(name: str, search_dirs: list[Path]) -> Path | None:
        """Find an image/video file tolerating different zero-padding styles."""
        p = Path(name)
        stem, suffix = p.stem, p.suffix

        import re as _re
        m = _re.search(r'\d+', stem)
        num = int(m.group()) if m else None
        prefix = stem[:m.start()] if m else stem
        postfix = stem[m.end():] if m else ""

        candidates: list[str] = []
        if num is not None:
            for ext in (".mp4", suffix, ".png", ".jpg", ".jpeg", ".webp"):
                for pad in (0, 2, 3, 4):
                    fmt = f"{num:0{pad}d}" if pad else str(num)
                    candidates.append(f"{prefix}{fmt}{postfix}{ext}")
        else:
            candidates = [p.with_suffix(".mp4").name, name]

        unique = list(dict.fromkeys(candidates))
        for d in search_dirs:
            for c in unique:
                full = d / c
                if full.exists():
                    return full
        return None

    def _resolve_image_paths_legacy(self) -> None:
        """Resolve image paths for projects that don't use an images/ folder."""
        search_dirs = [self.project_dir, self.project_dir / "images"]
        for scene in self.config.scenes:
            if Path(scene.image).is_absolute() and Path(scene.image).exists():
                continue
            found = self._find_image(Path(scene.image).name, search_dirs)
            if found:
                scene.image = str(found)

    @staticmethod
    def _make_title_slug(title: str) -> str:
        """Return a filesystem-safe folder name from the first 3 words of title."""
        import re
        words = [w for w in title.split() if w][:3]
        slug = "_".join(words)
        slug = re.sub(r"[^\w]", "_", slug)
        slug = re.sub(r"_+", "_", slug)
        return slug.strip("_") or "project"

    @property
    def title(self) -> str:
        return self.config.title

    @property
    def project_output_dir(self) -> Path:
        """Per-project output root: <project_dir>/output/<title_slug>/"""
        return self.project_dir / "output" / self.title_slug

    @property
    def title_slug(self) -> str:
        """First 3 words of the title, joined with underscores, safe for filenames."""
        return self._make_title_slug(self.config.title)

    @property
    def scenes(self) -> list[SceneConfig]:
        return self.config.scenes

    @property
    def scene_count(self) -> int:
        return len(self.config.scenes)

    @property
    def output_path(self) -> Path:
        out = Path(self.config.output)
        if out.is_absolute():
            return out
        return self.project_output_dir / out.name

    def get_missing_images(self) -> list[str]:
        """Return list of scene images that don't exist on disk."""
        missing = []
        for scene in self.config.scenes:
            if not Path(scene.image).exists():
                missing.append(scene.image)
        return missing

    def validate(self) -> list[str]:
        """Full validation. Returns list of error messages (empty = valid)."""
        errors = []
        missing = self.get_missing_images()
        if missing:
            for m in missing:
                errors.append(f"Image not found: {m}")

        total = len(self.config.scenes)
        for i, scene in enumerate(self.config.scenes):
            if not scene.script.strip():
                errors.append(
                    f"Scene {i + 1}: script is empty — "
                    f"your project.json has fewer scenes than media files on disk "
                    f"({total} scenes discovered, add more scripts to cover all media)."
                )
            
            # Check media integrity if it exists on disk
            img_path = Path(scene.image)
            if img_path.exists() and img_path.is_file():
                try:
                    if img_path.stat().st_size == 0:
                        errors.append(f"Scene {i + 1}: Image file '{img_path.name}' is empty (0 bytes).")
                    elif not is_clip_path(img_path):
                        from PIL import Image
                        with Image.open(img_path) as img:
                            img.verify()
                except Exception as e:
                    errors.append(f"Scene {i + 1}: Image file '{img_path.name}' is corrupted or invalid ({e}).")

        return errors


def load_project(json_path: str | Path) -> Project:
    """Load and validate a project from a JSON file."""
    json_path = Path(json_path).resolve()

    if not json_path.exists():
        raise InvalidProjectError(str(json_path), "File does not exist.")

    if not json_path.suffix.lower() == ".json":
        raise InvalidProjectError(str(json_path), "File must be a .json file.")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f, strict=False)
    except json.JSONDecodeError as e:
        raise InvalidProjectError(str(json_path), f"Invalid JSON: {e}")

    try:
        config = ProjectConfig(**data)
    except Exception as e:
        raise InvalidProjectError(str(json_path), str(e))

    project_dir = json_path.parent
    return Project(config=config, project_dir=project_dir, json_path=json_path)
