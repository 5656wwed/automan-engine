"""Kokoro TTS provider (OpenAI-compatible local/GPU server)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.kokoro")

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
    provider_name = "kokoro"

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url or os.environ.get("KOKORO_URL", "http://localhost:8002/v1")
        self._model = os.environ.get("KOKORO_MODEL", "kokoro")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self._base_url,
                                  api_key=os.environ.get("KOKORO_API_KEY", "kokoro"))
        return self._client

    def is_available(self) -> bool:
        return True

    async def generate(self, text, output_path, voice_id="af_heart", speed=1.0,
                       pitch=1.0, stability=0.5, emotion=None, **kwargs):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def _gen():
            self._get_client().audio.speech.create(
                model=self._model, voice=voice_id, input=text,
                speed=speed, response_format="mp3").stream_to_file(str(output_path))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _gen)
        from app.utils.audio import get_audio_duration
        d = get_audio_duration(output_path)
        log.info(f"Generated Kokoro audio: {output_path.name} ({d:.1f}s)")
        return TTSResult(audio_path=output_path, duration=d, voice_id=voice_id, text=text)

    async def list_voices(self) -> list[Voice]:
        return [Voice(voice_id=v, name=n, provider=self.provider_name, language="en", gender=g)
                for v, n, g in KOKORO_VOICES]
