"""Abstract TTS provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Voice:
    """Represents an available voice."""
    voice_id: str
    name: str
    provider: str
    language: str = "en"
    gender: str = "unknown"
    preview_url: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name} ({self.voice_id}) [{self.provider}]"


@dataclass
class TTSResult:
    """Result of a TTS generation call."""
    audio_path: Path
    duration: float  # seconds
    voice_id: str
    text: str
    cached: bool = False
    word_timestamps: Optional[dict] = None  # populated by providers that support it (e.g. Inworld)


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    provider_name: str = "base"

    @abstractmethod
    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "default",
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        """Generate speech audio from text.

        Args:
            text: The script/narration text.
            output_path: Where to save the generated audio file.
            voice_id: Provider-specific voice identifier.
            speed: Speech speed multiplier (0.5-2.0).
            pitch: Pitch adjustment (0.5-2.0).
            stability: Voice stability/consistency (0.0-1.0).
            emotion: Optional emotion hint.

        Returns:
            TTSResult with path, duration, and metadata.
        """
        ...

    @abstractmethod
    async def list_voices(self) -> list[Voice]:
        """List all available voices from this provider."""
        ...

    async def clone_voice(
        self,
        name: str,
        audio_path: str | Path,
        description: str = "",
    ) -> Voice:
        """Clone a voice from an audio sample. Not all providers support this."""
        raise NotImplementedError(
            f"{self.provider_name} does not support voice cloning."
        )

    async def preview_voice(
        self,
        voice_id: str,
        text: str = "Hello, this is a voice preview for AutoScene Studio.",
    ) -> Path:
        """Generate a short preview clip. Default implementation uses generate()."""
        from app.core.config import get_config
        config = get_config()
        preview_path = config.cache_dir / "previews" / f"{voice_id}_preview.mp3"
        preview_path.parent.mkdir(parents=True, exist_ok=True)

        if preview_path.exists():
            return preview_path

        result = await self.generate(
            text=text,
            output_path=preview_path,
            voice_id=voice_id,
        )
        return result.audio_path

    async def get_voice(self, voice_id: str) -> Optional[Voice]:
        """Fetch details for a single voice by ID. 
        Default implementation searches the full list.
        """
        voices = await self.list_voices()
        for v in voices:
            if v.voice_id == voice_id:
                return v
        return None

    def is_available(self) -> bool:
        """Check if this provider is properly configured (API keys, etc)."""
        return True
