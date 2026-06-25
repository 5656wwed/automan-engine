"""Edge TTS provider — free, no API key needed."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.edge")


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge TTS — free, high-quality, 300+ voices."""

    provider_name = "edge"

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "en-US-GuyNeural",
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build rate/pitch strings for edge-tts
        rate_str = f"{int((speed - 1.0) * 100):+d}%"
        pitch_str = f"{int((pitch - 1.0) * 50):+d}Hz"

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_id,
            rate=rate_str,
            pitch=pitch_str,
        )

        await communicate.save(str(output_path))

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)

        log.info(f"Generated Edge TTS audio: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        import edge_tts

        raw_voices = await edge_tts.list_voices()
        voices = []
        for v in raw_voices:
            voices.append(Voice(
                voice_id=v["ShortName"],
                name=v["FriendlyName"],
                provider=self.provider_name,
                language=v.get("Locale", "en-US"),
                gender=v.get("Gender", "unknown").lower(),
                metadata={
                    "locale": v.get("Locale"),
                    "voice_type": v.get("VoiceType"),
                },
            ))
        log.info(f"Edge TTS voices loaded: {len(voices)} total")
        return voices
