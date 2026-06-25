"""OpenAI TTS provider integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.core.config import get_config
from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.openai")

# Available OpenAI voices
OPENAI_VOICES = [
    ("alloy", "Alloy", "neutral"),
    ("echo", "Echo", "male"),
    ("fable", "Fable", "male"),
    ("onyx", "Onyx", "male"),
    ("nova", "Nova", "female"),
    ("shimmer", "Shimmer", "female"),
]


class OpenAIProvider(TTSProvider):
    """OpenAI TTS provider."""

    provider_name = "openai"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or get_config().openai_api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self._api_key)
            except ImportError:
                raise RuntimeError("OpenAI SDK not installed. Run: pip install openai")
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key != "your_openai_api_key_here")

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "onyx",
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        model = kwargs.get("model", "tts-1-hd")

        def _generate_sync():
            client = self._get_client()
            response = client.audio.speech.create(
                model=model,
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

        log.info(f"Generated OpenAI audio: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        return [
            Voice(
                voice_id=vid,
                name=name,
                provider=self.provider_name,
                language="en",
                gender=gender,
            )
            for vid, name, gender in OPENAI_VOICES
        ]
