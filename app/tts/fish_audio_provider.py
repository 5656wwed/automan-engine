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
# The free/slow Fish models can take minutes on a long narration line: measured
# ~0.5 s per character, so a 245-char scene line took 118 s. A flat small timeout
# (this was 15 s) killed the FIRST scene of every render with an empty message,
# because asyncio.TimeoutError stringifies to "". Budget per request instead.
MIN_TIMEOUT = 120      # seconds — floor for short lines
MAX_TIMEOUT = 900      # seconds — ceiling so a hung request cannot stall forever
SECONDS_PER_CHAR = 1.5  # ~3x the measured 0.5 s/char, headroom for load
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=MIN_TIMEOUT)


def _timeout_for(text: str) -> aiohttp.ClientTimeout:
    """Timeout sized to the narration length, not a fixed guess."""
    budget = min(MAX_TIMEOUT, max(MIN_TIMEOUT, int(len(text or "") * SECONDS_PER_CHAR)))
    return aiohttp.ClientTimeout(total=budget, sock_connect=30, sock_read=budget)


def _describe(e: BaseException) -> str:
    """Never return an empty message — asyncio.TimeoutError str()s to ''."""
    msg = str(e).strip()
    return f"{type(e).__name__}: {msg}" if msg else f"{type(e).__name__} (no message from the server)"


class FishRetryableError(RuntimeError):
    """Transient Fish Audio failure (timeout, 429, 5xx) — safe to retry."""


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
        headers["model"] = kwargs.get("model", "s2.1-pro-free")  # free tier; change to s2.1-pro or s2-pro for paid

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

        timeout = _timeout_for(text)
        attempts = max(1, int(kwargs.get("retries", 1)) + 1)
        audio_bytes = b""
        for attempt in range(1, attempts + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status != 200:
                            try:
                                err_data = await resp.json()
                                error_msg = (err_data.get("message") or err_data.get("detail")
                                             or str(err_data))
                            except Exception:
                                error_msg = (await resp.text())[:300]
                            msg = f"Fish Audio TTS failed: HTTP {resp.status} — {error_msg}"
                            if resp.status in (408, 429, 500, 502, 503, 504):
                                raise FishRetryableError(msg)
                            raise RuntimeError(msg)

                        audio_bytes = await resp.read()
                break
            except RuntimeError as e:
                if not isinstance(e, FishRetryableError) or attempt >= attempts:
                    raise
                log.warning(f"Fish Audio TTS attempt {attempt}/{attempts}: {e}")
                await asyncio.sleep(3 * attempt)
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                log.warning(f"Fish Audio TTS attempt {attempt}/{attempts} failed ({_describe(e)}); "
                            f"budget was {timeout.total}s for {len(text)} chars")
                if attempt >= attempts:
                    raise RuntimeError(
                        f"Fish Audio TTS failed after {attempts} attempt(s): {_describe(e)}. "
                        f"The voice/key are fine — the API was too slow for this line "
                        f"({len(text)} chars, {timeout.total}s allowed), or the connection dropped."
                    )
                await asyncio.sleep(3 * attempt)

        if not audio_bytes:
            raise RuntimeError("Fish Audio TTS returned no audio data.")

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

        import os as _os
        extra = _os.environ.get("FISH_EXTRA_VOICES", "")

        # When FISH_EXTRA_VOICES is set, show ONLY those curated voices —
        # do NOT flood the dropdown with every public/clone model on the account.
        # A file at FISH_VOICES_FILE (one "id|Title" per line) is also supported,
        # since systemd's Environment= cannot hold names with spaces/parens.
        if not extra.strip():
            _voices_file = _os.environ.get("FISH_VOICES_FILE", "")
            if not _voices_file:
                _voices_file = str(Path(__file__).resolve().parent.parent.parent / "fish_voices.txt")
            _vf = Path(_voices_file)
            if _vf.exists():
                extra = "\n".join(l for l in _vf.read_text(encoding="utf-8").splitlines() if l.strip())

        if extra.strip():
            voices: list[Voice] = []
            for piece in extra.replace("\n", ";").split(";"):
                piece = piece.strip()
                if not piece or "|" not in piece:
                    continue
                vid, title = piece.split("|", 1)
                vid, title = vid.strip(), title.strip()
                if vid and title:
                    voices.append(Voice(
                        voice_id=vid, name=f"{title} (FishAudio)",
                        provider=self.provider_name, language="en",
                        gender="unknown", preview_url=None,
                        metadata={"type": "model", "is_clone": False},
                    ))
            log.info(f"Fish Audio voices loaded (curated only): {len(voices)} total")
            return voices

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
