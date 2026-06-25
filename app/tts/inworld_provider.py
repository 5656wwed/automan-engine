"""Inworld AI TTS provider integration."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import aiohttp

from app.core.exceptions import TTSError
from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.inworld")

BASE_URL = "https://api.inworld.ai"
DEFAULT_MODEL = "inworld-tts-2"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Inworld AI premade voices — (voice_id, display_name, gender)
INWORLD_PREMADE_VOICES: list[tuple[str, str, str]] = [
    # Workspace custom voices
    ("default-xtytd8coit3byx-lffsuog__alied", "Allied", "male"),
    ("default-xtytd8coit3byx-lffsuog__design-voice-e6edc5bf", "Ancient Man", "male"),
    ("default-xtytd8coit3byx-lffsuog__jordan", "Jordan", "male"),
    ("default-xtytd8coit3byx-lffsuog__stark", "Stark", "male"),
    # Male
    ("Alex", "Alex", "male"),
    ("Antoni", "Antoni", "male"),
    ("Arnold", "Arnold", "male"),
    ("Callum", "Callum", "male"),
    ("Charlie", "Charlie", "male"),
    ("Chris", "Chris", "male"),
    ("Clyde", "Clyde", "male"),
    ("Daniel", "Daniel", "male"),
    ("Dennis", "Dennis", "male"),
    ("Drew", "Drew", "male"),
    ("Ethan", "Ethan", "male"),
    ("Giovanni", "Giovanni", "male"),
    ("Harry", "Harry", "male"),
    ("James", "James", "male"),
    ("Jeremy", "Jeremy", "male"),
    ("Joseph", "Joseph", "male"),
    ("Josh", "Josh", "male"),
    ("Liam", "Liam", "male"),
    ("Michael", "Michael", "male"),
    ("Patrick", "Patrick", "male"),
    ("Paul", "Paul", "male"),
    ("Roger", "Roger", "male"),
    ("Sam", "Sam", "male"),
    ("Thomas", "Thomas", "male"),
    ("Will", "Will", "male"),
    ("Xander", "Xander", "male"),
    # Female
    ("Aria", "Aria", "female"),
    ("Bella", "Bella", "female"),
    ("Bria", "Bria", "female"),
    ("Charlotte", "Charlotte", "female"),
    ("Dorothy", "Dorothy", "female"),
    ("Elli", "Elli", "female"),
    ("Emily", "Emily", "female"),
    ("Freya", "Freya", "female"),
    ("Gigi", "Gigi", "female"),
    ("Glinda", "Glinda", "female"),
    ("Grace", "Grace", "female"),
    ("Jessica", "Jessica", "female"),
    ("Laura", "Laura", "female"),
    ("Lily", "Lily", "female"),
    ("Matilda", "Matilda", "female"),
    ("Nicole", "Nicole", "female"),
    ("Rachel", "Rachel", "female"),
    ("Sarah", "Sarah", "female"),
    ("Serena", "Serena", "female"),
]


def _stability_to_delivery_mode(stability: float) -> str:
    """Map stability (0.0-1.0) to Inworld deliveryMode."""
    if stability < 0.33:
        return "STABLE"
    if stability < 0.66:
        return "BALANCED"
    return "CREATIVE"


class InworldProvider(TTSProvider):
    """Inworld AI TTS provider."""

    provider_name = "inworld"

    def __init__(
        self,
        api_key: Optional[str] = None,
        custom_voices: Optional[list[dict]] = None,
    ):
        self._api_key = api_key
        self._custom_voices: list[dict] = custom_voices or []

    def update_custom_voices(self, custom_voices: list[dict]) -> None:
        self._custom_voices = custom_voices

    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _headers(self) -> dict:
        return {
            "Authorization": f"Basic {self._api_key}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "Dennis",
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        if not self.is_available():
            raise TTSError("inworld", "API key not configured")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # pitch and emotion are not supported by the Inworld TTS API

        model_id = kwargs.get("model_id", DEFAULT_MODEL)
        want_timestamps = kwargs.get("want_timestamps", False)

        payload = {
            "text": text,
            "voiceId": voice_id,
            "modelId": model_id,
            "audioConfig": {
                "audioEncoding": "MP3",
                "sampleRateHertz": 22050,
                "speakingRate": speed,
            },
            "deliveryMode": _stability_to_delivery_mode(stability),
            "applyTextNormalization": "ON",
        }
        if want_timestamps:
            payload["timestampType"] = "WORD"

        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/tts/v1/voice",
                headers=self._headers(),
                json=payload,
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    message = data.get("message", f"HTTP {resp.status}")
                    raise TTSError("inworld", message)

                audio_b64 = data.get("audioContent")
                if not audio_b64:
                    raise TTSError("inworld", f"Missing audioContent in response: {data}")
                output_path.write_bytes(base64.b64decode(audio_b64))
                word_timestamps = data.get("timestampInfo") if want_timestamps else None

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)

        log.info(f"Generated Inworld audio: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
            word_timestamps=word_timestamps,
        )

    async def list_voices(self) -> list[Voice]:
        custom = [
            Voice(
                voice_id=v["id"],
                name=v["name"],
                provider=self.provider_name,
                metadata={"custom": True, "is_clone": True},
            )
            for v in self._custom_voices
        ]

        # Try live fetch if we have a key; fall back to hardcoded list.
        api_voices = await self._fetch_voices_from_api() if self._api_key else []

        if api_voices:
            combined = custom + api_voices
        else:
            premade = [
                Voice(
                    voice_id=vid,
                    name=name,
                    provider=self.provider_name,
                    gender=gender,
                    metadata={"custom": False},
                )
                for vid, name, gender in INWORLD_PREMADE_VOICES
            ]
            combined = custom + premade

        # Deduplicate by voice_id, preserving order (custom voices win)
        seen: set[str] = set()
        result: list[Voice] = []
        for v in combined:
            if v.voice_id not in seen:
                seen.add(v.voice_id)
                result.append(v)
        return result

    async def _fetch_voices_from_api(self) -> list[Voice]:
        """Fetch available voices from Inworld's /tts/v1/voices endpoint."""
        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.get(
                    f"{BASE_URL}/tts/v1/voices",
                    headers=self._headers(),
                ) as resp:
                    if resp.status != 200:
                        log.warning(f"Inworld voice list returned HTTP {resp.status}")
                        return []
                    data = await resp.json()

            raw = data.get("voices") or data.get("voice") or []
            if not isinstance(raw, list):
                return []

            voices = []
            for v in raw:
                vid = v.get("voiceId") or v.get("voice_id") or v.get("id") or ""
                name = v.get("name") or v.get("displayName") or vid
                gender = (v.get("gender") or "unknown").lower()
                if vid:
                    voices.append(Voice(
                        voice_id=vid,
                        name=name,
                        provider=self.provider_name,
                        gender=gender,
                        metadata={"custom": False},
                    ))
            log.info(f"Fetched {len(voices)} voices from Inworld API")
            return voices
        except Exception as e:
            log.warning(f"Could not fetch Inworld voices from API: {e}")
            return []
