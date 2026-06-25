"""Project model — JSON schema definition and validation."""

from __future__ import annotations

import json
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
    script: str
    overlay_text: Optional[Union[str, list[OverlayItem]]] = None
    transition: Optional[str] = None
    motion: Optional[str] = None
    duration_padding: Optional[float] = Field(default=None, ge=0.0, le=10.0)
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
    quality: Optional[str] = None
    subtitles_enabled: bool = False
    subtitles_style: str = "auto"
    font_path: Optional[str] = None
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
def _numeric_stem(p: Path) -> int:
    """Sort key: extract the first integer from a filename stem."""
    import re as _re
    m = _re.search(r'\d+', p.stem)
    return int(m.group()) if m else 0


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

        Order: MP4 files sorted by numeric stem FIRST, then image files
        sorted by numeric stem. This gives the caller full control over
        scene count — adding 001.mp4–010.mp4 alongside 001.png–072.png
        produces 82 media entries, not 72.
        """
        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

        search_root = self.project_dir / "images"
        if not search_root.exists():
            search_root = self.project_dir

        mp4s = sorted(
            [f for f in search_root.iterdir() if f.is_file() and f.suffix.lower() == ".mp4"],
            key=_numeric_stem,
        )
        images = sorted(
            [f for f in search_root.iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_EXTS],
            key=_numeric_stem,
        )
        return mp4s + images

    def _build_scene_list(self) -> None:
        """Rebuild config.scenes from discovered media files.

        Each media file becomes one scene. JSON scene configs supply the
        script, voice, overlay, etc. positionally — scene config [i] is
        paired with media file [i]. If there are more media files than
        JSON scenes, the extra media files inherit the last scene's voice
        config and get an empty script (validation will flag those).
        If there are more JSON scenes than media files, the extra scenes
        are silently dropped.
        """
        all_media = self._discover_media()

        if not all_media:
            # Nothing on disk — keep JSON scenes and resolve paths normally
            self._resolve_image_paths_legacy()
            return

        json_scenes = self.config.scenes
        new_scenes: list[SceneConfig] = []

        for i, media_path in enumerate(all_media):
            if i < len(json_scenes):
                base = json_scenes[i]
                scene = base.model_copy(update={"image": str(media_path)})
            else:
                # More media than scripts — create a minimal scene
                template = json_scenes[-1] if json_scenes else None
                scene = SceneConfig(
                    image=str(media_path),
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
                    elif img_path.suffix.lower() != ".mp4":
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
