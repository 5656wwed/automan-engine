"""ElevenLabs TTS provider integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.core.config import get_config
from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.elevenlabs")


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs TTS provider using the official SDK."""

    provider_name = "elevenlabs"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or get_config().elevenlabs_api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from elevenlabs.client import ElevenLabs
                self._client = ElevenLabs(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "ElevenLabs SDK not installed. Run: pip install elevenlabs"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to initialize ElevenLabs client: {e}")
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key != "your_elevenlabs_api_key_here")

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def _generate_sync():
            client = self._get_client()

            voice_settings = {
                "stability": stability,
                "similarity_boost": 0.75,
                "speed": speed,
            }

            audio_generator = client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id="eleven_multilingual_v2",
                voice_settings=voice_settings,
            )

            # Write audio chunks to file
            with open(output_path, "wb") as f:
                for chunk in audio_generator:
                    f.write(chunk)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _generate_sync)

        # Get duration
        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)

        log.info(f"Generated ElevenLabs audio: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        def _list_sync():
            client = self._get_client()
            response = client.voices.get_all()
            voices = []
            for v in response.voices:
                voices.append(Voice(
                    voice_id=v.voice_id,
                    name=v.name,
                    provider=self.provider_name,
                    language=v.labels.get("language", "en") if v.labels else "en",
                    gender=v.labels.get("gender", "unknown") if v.labels else "unknown",
                    preview_url=v.preview_url,
                    metadata={"category": v.category},
                ))
            return voices

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _list_sync)

    async def clone_voice(
        self,
        name: str,
        audio_path: str | Path,
        description: str = "",
    ) -> Voice:
        def _clone_sync():
            client = self._get_client()
            voice = client.voices.ivc.create(
                name=name,
                description=description or f"Cloned voice: {name}",
                files=[str(audio_path)],
            )
            return Voice(
                voice_id=voice.voice_id,
                name=name,
                provider=self.provider_name,
                metadata={"cloned": True},
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _clone_sync)
        log.info(f"Cloned voice '{name}' → {result.voice_id}")
    async def get_voice(self, voice_id: str) -> Optional[Voice]:
        def _get_sync():
            try:
                client = self._get_client()
                v = client.voices.get(voice_id)
                return Voice(
                    voice_id=v.voice_id,
                    name=v.name,
                    provider=self.provider_name,
                    language=v.labels.get("language", "en") if v.labels else "en",
                    gender=v.labels.get("gender", "unknown") if v.labels else "unknown",
                    preview_url=v.preview_url,
                    metadata={"category": v.category},
                )
            except Exception:
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_sync)
