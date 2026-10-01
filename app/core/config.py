"""Global configuration and settings management."""

from __future__ import annotations

import os
import json
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Load .env from project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_PATH)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TTSProvider(str, Enum):
    ELEVENLABS = "elevenlabs"
    OPENAI = "openai"
    EDGE = "edge"
    AI33PRO = "ai33pro"
    FISHAUDIO = "fishaudio"
    INWORLD = "inworld"
    POCKET = "pocket"
    KOKORO = "kokoro"


class MotionType(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    ZOOM_IN_LEFT = "zoom_in_left"
    ZOOM_IN_RIGHT = "zoom_in_right"
    ZOOM_OUT_LEFT = "zoom_out_left"
    ZOOM_OUT_RIGHT = "zoom_out_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    CAMERA_DRIFT = "camera_drift"
    # Punch-in shots used to re-cut a held still mid-beat: each one STARTS at a
    # visibly tighter framing than a normal Ken Burns move (1.30 vs 1.0), so the
    # boundary between shots reads as a hard cut, not a continuous drift.
    CUT_IN = "cut_in"
    CUT_OUT = "cut_out"
    NONE = "none"


class TransitionType(str, Enum):
    NONE = "none"
    FADE = "fade"
    DISSOLVE = "dissolve"
    DIP_TO_BLACK = "dip_to_black"
    CINEMATIC_BLUR = "cinematic_blur"
    CROSS_ZOOM = "cross_zoom"


class AspectRatio(str, Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class QualityPreset(str, Enum):
    LOW = "low"          # CRF 28, fast
    MEDIUM = "medium"    # CRF 23, medium
    HIGH = "high"        # CRF 18, slow
    ULTRA = "ultra"      # CRF 15, veryslow


# ---------------------------------------------------------------------------
# Settings Models
# ---------------------------------------------------------------------------
class ExportSettings(BaseModel):
    """Video export configuration."""
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    resolution: str = Field(default="1920x1080", pattern=r"^\d+x\d+$")
    fps: int = Field(default=30, ge=1, le=120)
    quality: QualityPreset = QualityPreset.HIGH
    codec: str = os.environ.get("AUTOMAN_CODEC", "auto")
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    pixel_format: str = "yuv420p"

    @property
    def width(self) -> int:
        return int(self.resolution.split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split("x")[1])

    @property
    def crf(self) -> int:
        return {"low": 28, "medium": 23, "high": 18, "ultra": 15}[self.quality.value]

    @property
    def preset_speed(self) -> str:
        return {
            "low": "ultrafast",
            "medium": "medium",
            "high": "slow",
            "ultra": "veryslow",
        }[self.quality.value]


class TTSSettings(BaseModel):
    """Default TTS settings."""
    provider: TTSProvider = TTSProvider.EDGE
    voice_id: str = "en-US-GuyNeural"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=1.0, ge=0.5, le=2.0)
    stability: float = Field(default=0.5, ge=0.0, le=1.0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    clone_voice: bool = False


class RenderSettings(BaseModel):
    """Default render pipeline settings."""
    default_transition: TransitionType = TransitionType.NONE
    transition_duration: float = Field(default=0.5, ge=0.1, le=3.0)
    default_motion: MotionType = MotionType.ZOOM_OUT
    randomize_motion: bool = True
    # Silence kept after each narration line. This is the ONLY dead air in the
    # final video (the transition overlap cancels out), so a fast-paced
    # documentary wants it small — 0.12 s keeps the picture cutting on the
    # voice instead of lingering after it. $AUTOMAN_PADDING overrides.
    duration_padding: float = Field(
        default=float(os.environ.get("AUTOMAN_PADDING", "0.12") or 0.12), ge=0.0, le=5.0)
    # Split a still [IMAGE] beat into several shots (alternating motion) so the
    # picture changes mid-beat instead of freezing for the whole line.
    # 0 = off. $AUTOMAN_PICTURE_CUT overrides.
    picture_cut_seconds: float = Field(
        default=float(os.environ.get("AUTOMAN_PICTURE_CUT", "0") or 0), ge=0.0, le=30.0)
    # Fixed beat length (the pipeline's unit is an 8s beat: 60 beats = 8:00).
    # 0 = off, the picture follows the voice instead. $AUTOMAN_BEAT_SECONDS.
    beat_seconds: float = Field(
        default=float(os.environ.get("AUTOMAN_BEAT_SECONDS", "0") or 0), ge=0.0, le=60.0)
    # Free-form re-cut of a still beat: either a number of pictures per beat
    # (>=2), or a new picture every N seconds. Both 0 = one held picture.
    pictures_per_beat: int = Field(
        default=int(os.environ.get("AUTOMAN_PICTURES_PER_BEAT", "0") or 0), ge=0, le=12)
    cache_audio: bool = True


class AppConfig(BaseModel):
    """Master application configuration."""
    # API Keys
    elevenlabs_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    ai33pro_api_key: Optional[str] = None
    fish_audio_api_key: Optional[str] = None
    inworld_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    inworld_custom_voices: list[dict[str, str]] = Field(default_factory=list)

    # Paths
    ffmpeg_path: Optional[str] = None
    cache_dir: Path = _PROJECT_ROOT / ".cache"
    temp_dir: Path = _PROJECT_ROOT / ".tmp"

    # Overlay text settings
    overlay_font_size: int = 130
    overlay_sfx_volume: float = Field(default=0.55, ge=0.0, le=1.0)
    overlay_type_duration: float = Field(default=2.0, ge=0.5, le=5.0)
    overlay_font_path: Optional[str] = None

    # MP4 video scene settings
    mp4_bg_volume: float = Field(default=0.08, ge=0.0, le=1.0)

    # Background music
    bg_music_enabled: bool = False
    bg_music_volume: float = Field(default=0.20, ge=0.0, le=1.0)

    # Sub-configs
    export: ExportSettings = ExportSettings()
    tts: TTSSettings = TTSSettings()
    render: RenderSettings = RenderSettings()

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Global config loader
# ---------------------------------------------------------------------------
def _get_config_path() -> Path:
    """Get the path to the user-specific settings.json file."""
    if os.name == "nt": # Windows
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else: # Linux/macOS
        base = Path.home() / ".config"
    
    config_dir = base / "AutoSceneStudio"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "settings.json"


def save_config(config: AppConfig) -> None:
    """Save configuration to the user-specific settings.json."""
    path = _get_config_path()
    with open(path, "w") as f:
        f.write(config.model_dump_json(indent=2))


def load_config() -> AppConfig:
    """Load configuration from settings.json.

    API keys are NOT read from environment variables or any shipped
    default — they must be entered and saved by the user via the
    Settings UI. Only non-secret values (e.g. FFmpeg path) are
    accepted from the environment as a convenience.
    """
    path = _get_config_path()

    # Only non-secret env-driven values are honoured here.
    env_data = {
        "ffmpeg_path": os.getenv("FFMPEG_PATH"),
    }
    env_data = {k: v for k, v in env_data.items() if v}

    # Load from user-specific JSON if it exists (this is where
    # API keys live after the user saves them).
    json_data = {}
    if path.exists():
        try:
            with open(path, "r") as f:
                json_data = json.load(f)
        except Exception:
            pass

    # Merge: JSON overrides ENV
    merged_data = {**env_data, **json_data}

    try:
        config = AppConfig.model_validate(merged_data)
    except Exception:
        # Fallback to default if everything fails
        config = AppConfig()

    # Ensure directories exist
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.temp_dir.mkdir(parents=True, exist_ok=True)

    return config


# Singleton
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Get or create the global config singleton."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> AppConfig:
    """Force-reload the config singleton from disk."""
    global _config
    _config = load_config()
    return _config
