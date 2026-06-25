"""Fish Audio TTS provider integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import aiohttp

from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.fishaudio")

BASE_URL = "https://api.fish.audio"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)


class FishAudioProvider(TTSProvider):
    """Fish Audio TTS provider using their REST API."""

    provider_name = "fishaudio"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _headers(self, json_content: bool = True) -> dict:
        h = {"Authorization": f"Bearer {self._api_key}"}
        if json_content:
            h["Content-Type"] = "application/json"
        return h

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "",
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("Fish Audio API Key is not set.")
        if not voice_id:
            raise RuntimeError("Fish Audio: voice_id (model ID) is required.")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"{BASE_URL}/v1/tts"
        # model header is required for Fish Audio
        headers = self._headers()
        headers["model"] = kwargs.get("model", "s2-pro")

        # Map linear volume (1.0 = 100%) to Fish Audio dB range (-10 to +10)
        fa_volume = round(max(-10.0, min(10.0, (kwargs.get("volume", 1.0) - 1.0) * 10)), 1)

        payload = {
            "text": text,
            "reference_id": voice_id,
            "prosody": {
                "speed": speed,
                "volume": fa_volume,
            },
            "format": "mp3",
            "normalize": True,
        }

        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    try:
                        err_data = await resp.json()
                        error_msg = err_data.get("message", "Unknown error")
                    except:
                        error_msg = await resp.text()
                    raise RuntimeError(f"Fish Audio TTS failed: {error_msg}")

                audio_bytes = await resp.read()
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)
        log.info(f"Fish Audio audio saved: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        if not self._api_key:
            return []

        voices: list[Voice] = []
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            # 1. Fetch personal cloned voices
            await self._fetch_fish_voices(session, voices, self_only=True)
            # 2. Fetch public voices (first page)
            await self._fetch_fish_voices(session, voices, self_only=False)

        # Sort clones to the top
        voices.sort(key=lambda v: 0 if v.metadata.get("is_clone") else 1)
        log.info(f"Fish Audio voices loaded: {len(voices)} total")
        return voices

    async def _fetch_fish_voices(
        self, 
        session: aiohttp.ClientSession, 
        voices: list[Voice], 
        self_only: bool = False
    ) -> None:
        url = f"{BASE_URL}/model?page_size=100&page_number=1&self_only={'true' if self_only else 'false'}"
        try:
            async with session.get(url, headers=self._headers(False)) as resp:
                if resp.status != 200:
                    log.warning(f"Fish Audio: Failed to list models (self_only={self_only}, status={resp.status})")
                    return
                
                data = await resp.json()
                items = data.get("items", []) if isinstance(data, dict) else []
                
                for item in items:
                    voice_id = item.get("_id") or item.get("id")
                    if not voice_id:
                        continue
                        
                    # Extract basic info
                    name = item.get("title") or item.get("name") or "Unknown"
                    if self_only:
                        name = f"{name} (Clone)"
                    
                    lang = "en" # default
                    
                    voices.append(Voice(
                        voice_id=voice_id,
                        name=name,
                        provider=self.provider_name,
                        language=lang,
                        gender="unknown",
                        preview_url=None,
                        metadata={
                            "type": item.get("type", "model"),
                            "is_clone": self_only,
                            "visibility": item.get("visibility"),
                        },
                    ))
        except Exception as e:
            log.warning(f"Failed to fetch Fish Audio voices (self_only={self_only}): {e}")

    async def get_voice(self, voice_id: str) -> Optional[Voice]:
        """Fetch details for a single model ID from Fish Audio."""
        if not self._api_key or not voice_id:
            return None

        url = f"{BASE_URL}/model/{voice_id}"
        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.get(url, headers=self._headers(False)) as resp:
                    if resp.status != 200:
                        return None
                    
                    item = await resp.json()
                    name = item.get("title") or item.get("name") or "Unknown"
                    is_clone = item.get("visibility") == "private" # simple heuristic
                    
                    return Voice(
                        voice_id=voice_id,
                        name=name,
                        provider=self.provider_name,
                        language="en",
                        metadata={
                            "type": item.get("type"),
                            "is_clone": is_clone,
                        }
                    )
        except Exception:
            return None
