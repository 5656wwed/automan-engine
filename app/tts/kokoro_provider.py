"""Kokoro TTS provider (OpenAI-compatible local/GPU server).

Connects to a Kokoro FastAPI server exposing /v1/audio/speech (e.g. the
remsky/kokoro-fastapi image, or a local `kokoro` server). Point it at the
server with the KOKORO_URL env var (default http://localhost:8002/v1).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from app.core.config import get_config
from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.kokoro")

# A curated set of Kokoro voices (hexgrad/Kokoro-82M).
KOKORO_VOICES = [
    ("af_heart", "Heart (US female)", "female"),
    ("af_bella", "Bella (US female)", "female"),
    ("af_nicole", "Nicole (US female)", "female"),
    ("af_sarah", "Sarah (US female)", "female"),
    ("af_sky", "Sky (US female)", "female"),
    ("am_adam", "Adam (US male)", "male"),
    ("am_michael", "Michael (US male)", "male"),
    ("am_fenrir", "Fenrir (US male)", "male"),
    ("bf_emma", "Emma (UK female)", "female"),
    ("bf_isabella", "Isabella (UK female)", "female"),
    ("bm_george", "George (UK male)", "male"),
    ("bm_lewis", "Lewis (UK male)", "male"),
    ("ff_siwis", "Siwis (FR female)", "female"),
]


class KokoroProvider(TTSProvider):
    """Kokoro TTS via an OpenAI-compatible endpoint."""

    provider_name = "kokoro"

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url or os.environ.get(
            "KOKORO_URL", "http://localhost:8002/v1")
        self._model = os.environ.get("KOKORO_MODEL", "kokoro")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self._base_url,
                    api_key=os.environ.get("KOKORO_API_KEY", "kokoro"),
                )
            except ImportError:
                raise RuntimeError("OpenAI SDK not installed. Run: pip install openai")
        return self._client

    def is_available(self) -> bool:
        # Registered always (like inworld); generate() raises if the server is
        # down or the URL is wrong, so errors surface in the render log.
        return True

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "af_heart",
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
            response = client.audio.speech.create(
                model=self._model,
                voice=voice_id,
                input=text,
                speed=speed,
                response_format="mp3",
            )
            response.stream_to_file(str(output_path))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _generate_sync)

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)

        log.info(f"Generated Kokoro audio: {output_path.name} ({duration:.1f}s)")
        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        return [
            Voice(voice_id=vid, name=name, provider=self.provider_name,
                  language="en", gender=gender)
            for vid, name, gender in KOKORO_VOICES
        ]
