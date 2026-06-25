"""AI33Pro TTS provider — real API integration with async task polling.

Supports two backends behind the same API:
  * ElevenLabs (legacy /v1 endpoints)
  * Minimax    (/v1m endpoints — covers voice list, TTS, voice clones)

Voices fetched from Minimax are tagged with ``metadata["is_minimax"]``
so that ``generate()`` routes them through the /v1m/task/text-to-speech
endpoint with the correct Minimax payload shape.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

import aiohttp

from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.ai33pro")

BASE_URL = "https://api.ai33.pro"
POLL_INTERVAL = 2.0      # seconds between status checks
MAX_POLL_TIME = 300      # max seconds to wait for a single task (5 min)
TASK_RETRY_COUNT = 1     # automatic resubmits if a task times out
WAITING_LOG_INTERVAL = 30  # log "still waiting" every N seconds during poll
MINIMAX_PAGE_SIZE = 100  # voices per page when listing Minimax voices
MINIMAX_MAX_PAGES = 10   # safety cap on pagination
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)


class AI33ProProvider(TTSProvider):
    """AI33Pro TTS provider with support for ElevenLabs and Minimax backends."""

    provider_name = "ai33pro"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key
        # Cache of voice_id -> bool indicating if this voice should be
        # routed through the Minimax backend. Populated when list_voices
        # runs so generate() can dispatch correctly.
        self._minimax_voice_ids: set[str] = set()

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _headers(self, json_content: bool = True) -> dict:
        h = {"xi-api-key": self._api_key}
        if json_content:
            h["Content-Type"] = "application/json"
        return h

    # ------------------------------------------------------------------
    # Task polling
    # ------------------------------------------------------------------
    async def _poll_task(self, session: aiohttp.ClientSession, task_id: str) -> dict:
        """Poll task status until done or timeout.

        Minimax tail latency can spike during peak hours, so we use a
        generous ``MAX_POLL_TIME`` and surface a periodic ``still
        waiting`` log line so the UI doesn't look frozen. Transient
        polling errors (e.g. network blip, malformed JSON) are swallowed
        for one cycle and retried, rather than aborting the render.
        """
        url = f"{BASE_URL}/v1/task/{task_id}"
        start = time.time()
        last_status_log = start

        while time.time() - start < MAX_POLL_TIME:
            try:
                async with session.get(
                    url, headers=self._headers(json_content=False)
                ) as resp:
                    data = await resp.json()
            except Exception as e:
                # Don't abort the whole render on a single transient
                # poll error — wait and try again.
                log.debug(f"Task {task_id}: poll error (will retry): {e}")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            status = data.get("status", "")
            if status == "done":
                return data
            if status in ("failed", "error"):
                err = data.get("error_message", "Unknown error")
                raise RuntimeError(f"AI33Pro task failed: {err}")

            # Periodic visible heartbeat so the Logs tab shows life.
            now = time.time()
            if now - last_status_log >= WAITING_LOG_INTERVAL:
                elapsed = int(now - start)
                log.info(
                    f"AI33Pro task {task_id}: still {status or 'pending'} "
                    f"after {elapsed}s (timeout at {MAX_POLL_TIME}s)…"
                )
                last_status_log = now
            else:
                log.debug(f"Task {task_id}: {status} …")

            await asyncio.sleep(POLL_INTERVAL)

        raise TimeoutError(
            f"AI33Pro task {task_id} timed out after {MAX_POLL_TIME}s"
        )

    async def _submit_and_wait(
        self,
        session: aiohttp.ClientSession,
        url: str,
        payload: dict,
        label: str,
    ) -> dict:
        """Submit a TTS task and poll until done, retrying once on timeout.

        Returns the final task data (with ``metadata.audio_url``).
        """
        attempts = 1 + TASK_RETRY_COUNT
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            async with session.post(
                url, headers=self._headers(), json=payload
            ) as resp:
                result = await resp.json()
                if not result.get("success"):
                    raise RuntimeError(f"AI33Pro TTS request failed: {result}")
                task_id = result["task_id"]
                log.info(
                    f"AI33Pro task submitted ({label}) "
                    f"[attempt {attempt}/{attempts}]: {task_id}"
                )

            try:
                return await self._poll_task(session, task_id)
            except TimeoutError as e:
                last_error = e
                if attempt < attempts:
                    log.warning(
                        f"AI33Pro task {task_id} timed out — resubmitting "
                        f"(retry {attempt}/{TASK_RETRY_COUNT})."
                    )
                    continue
                raise

        # Shouldn't reach here, but mypy-friendly fallback.
        if last_error:
            raise last_error
        raise RuntimeError("AI33Pro: task did not complete")

    # ------------------------------------------------------------------
    # Backend detection
    # ------------------------------------------------------------------
    def _is_minimax_voice(self, voice_id: str, kwargs: dict) -> bool:
        """Best-effort guess at whether a voice id belongs to Minimax."""
        if kwargs.get("is_minimax"):
            return True
        if voice_id in self._minimax_voice_ids:
            return True
        # Minimax voice ids are typically all-digits (e.g. "209533299589184")
        # whereas ElevenLabs ids are alphanumeric tokens.
        return bool(voice_id) and voice_id.isdigit()

    # ------------------------------------------------------------------
    # generate
    # ------------------------------------------------------------------
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
            raise RuntimeError(
                "AI33Pro API Key is not set. Open Settings → API Keys to enter it."
            )
        if not voice_id:
            raise RuntimeError(
                "AI33Pro: voice_id is required. Pick a voice from the Voices tab."
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        is_minimax = self._is_minimax_voice(voice_id, kwargs)

        if is_minimax:
            url = f"{BASE_URL}/v1m/task/text-to-speech"
            payload = {
                "text": text,
                "model": kwargs.get("model", "speech-2.6-hd"),
                "voice_setting": {
                    "voice_id": voice_id,
                    "vol": float(kwargs.get("vol", kwargs.get("volume", 1.0))),
                    # GUI pitch is 0.5..2.0; Minimax expects -12..12 integer
                    "pitch": int(round((pitch - 1.0) * 12)),
                    "speed": float(speed),
                },
                "language_boost": kwargs.get("language_boost", "Auto"),
            }
        else:
            url = f"{BASE_URL}/v1/task/text-to-speech"
            payload = {
                "text": text,
                "voice_id": voice_id,
                "model_id": kwargs.get("model_id", "eleven_multilingual_v2"),
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": kwargs.get("similarity_boost", 0.75),
                    "speed": speed,
                },
            }

        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            # 1. Submit + poll (with one automatic retry on timeout).
            task_data = await self._submit_and_wait(
                session,
                url,
                payload,
                label="Minimax" if is_minimax else "ElevenLabs",
            )

            # 2. Pull the audio URL out of the completed task.
            audio_url = task_data.get("metadata", {}).get("audio_url")
            if not audio_url:
                raise RuntimeError("AI33Pro: no audio_url in completed task")

            # 3. Download audio
            async with session.get(audio_url) as resp:
                audio_bytes = await resp.read()
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)
        log.info(f"AI33Pro audio saved: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path, duration=duration,
            voice_id=voice_id, text=text,
        )

    # ------------------------------------------------------------------
    # list_voices
    # ------------------------------------------------------------------
    async def list_voices(self) -> list[Voice]:
        if not self._api_key:
            log.warning("AI33Pro: API key not set — skipping voice fetch")
            return []

        voices: list[Voice] = []
        # Reset and rebuild the Minimax routing cache each time we refresh.
        self._minimax_voice_ids.clear()

        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            await self._fetch_elevenlabs_voices(session, voices)
            await self._fetch_minimax_public_voices(session, voices)
            await self._fetch_minimax_clone_voices(session, voices)

        # Reorder so the user's cloned voices appear first — otherwise
        # they get visually drowned by the hundreds of public Minimax
        # voices that follow. We also keep the original relative order
        # within each group (stable sort).
        clone_count = sum(1 for v in voices if v.metadata.get("is_clone"))
        voices.sort(key=lambda v: 0 if v.metadata.get("is_clone") else 1)

        log.info(
            f"AI33Pro voices loaded: {len(voices)} total "
            f"({len(self._minimax_voice_ids)} Minimax, {clone_count} clones)"
        )
        return voices

    async def _fetch_elevenlabs_voices(
        self, session: aiohttp.ClientSession, voices: list[Voice]
    ) -> None:
        """ElevenLabs-backed voices (/v1/voices).

        This returns both the public premade catalogue AND any voices
        the user has cloned via the ElevenLabs side of AI33Pro. The
        ElevenLabs response carries a ``category`` field — values like
        ``cloned`` / ``professional`` / ``generated`` — which we surface
        as ``metadata["is_clone"]`` so the UI can mark them visually.
        """
        try:
            async with session.get(
                f"{BASE_URL}/v1/voices", headers=self._headers(False)
            ) as resp:
                if resp.status != 200:
                    # Fallback to alternative endpoint if /v1/voices 404s
                    async with session.get(
                        f"{BASE_URL}/v1/elevenlabs/voices", headers=self._headers(False)
                    ) as resp2:
                        if resp2.status == 200 and "application/json" in resp2.headers.get("Content-Type", "").lower():
                            data = await resp2.json()
                        else:
                            log.debug(f"AI33Pro ElevenLabs voices returned status {resp.status}")
                            return
                else:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "application/json" not in content_type:
                        log.debug(f"AI33Pro ElevenLabs voices returned non-JSON mimetype: {content_type}")
                        return
                    data = await resp.json()
                raw_voices = data.get("voices", []) if isinstance(data, dict) else []
                for v in raw_voices:
                    labels = v.get("labels") if isinstance(v.get("labels"), dict) else {}
                    category = (v.get("category") or "").lower()
                    is_clone = category in ("cloned", "professional", "generated")
                    name = v.get("name", "Unknown")
                    if is_clone and "(Clone)" not in name:
                        name = f"{name} (Clone)"
                    voices.append(Voice(
                        voice_id=v.get("voice_id", ""),
                        name=name,
                        provider=self.provider_name,
                        language=labels.get("language", "en"),
                        gender=labels.get("gender", "unknown"),
                        preview_url=v.get("preview_url"),
                        metadata={
                            "backend": "elevenlabs",
                            "category": category or "premade",
                            "is_clone": is_clone,
                        },
                    ))
        except Exception as e:
            log.warning(f"Failed to fetch ElevenLabs voices from AI33Pro: {e}")

    async def _fetch_minimax_public_voices(
        self, session: aiohttp.ClientSession, voices: list[Voice]
    ) -> None:
        """Minimax public voice catalog (POST /v1m/voice/list, paginated)."""
        page = 1
        while page <= MINIMAX_MAX_PAGES:
            payload = {"page": page, "page_size": MINIMAX_PAGE_SIZE, "tag_list": []}
            try:
                async with session.post(
                    f"{BASE_URL}/v1m/voice/list",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        log.debug(f"AI33Pro Minimax list returned status {resp.status}")
                        return
                    
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "application/json" not in content_type:
                        log.debug(f"AI33Pro Minimax list returned non-JSON mimetype: {content_type}")
                        return
                        
                    data = await resp.json()
            except Exception as e:
                log.warning(f"Failed to fetch Minimax public voices (page {page}): {e}")
                return

            # Some deployments return success at the top, others just the data.
            container = data.get("data") if isinstance(data, dict) else None
            if not container:
                if page == 1:
                    log.warning(
                        f"Minimax voice list returned no data on page 1: {data!r}"
                    )
                return

            v_list = container.get("voice_list", []) or []
            for v in v_list:
                vid = str(v.get("voice_id", ""))
                if not vid:
                    continue
                tags = v.get("tag_list") or []
                language = tags[0] if len(tags) >= 1 else "Auto"
                gender = next(
                    (t for t in tags if t.lower() in ("male", "female")),
                    "unknown",
                )
                voices.append(Voice(
                    voice_id=vid,
                    name=v.get("voice_name", "Unknown"),
                    provider=self.provider_name,
                    language=language,
                    gender=gender,
                    preview_url=v.get("sample_audio"),
                    metadata={
                        "backend": "minimax",
                        "is_minimax": True,
                        "tags": tags,
                    },
                ))
                self._minimax_voice_ids.add(vid)

            has_more = bool(container.get("has_more"))
            if not has_more or not v_list:
                break
            page += 1

    async def _fetch_minimax_clone_voices(
        self, session: aiohttp.ClientSession, voices: list[Voice]
    ) -> None:
        """User-owned Minimax cloned voices (GET /v1m/voice/clone)."""
        try:
            async with session.get(
                f"{BASE_URL}/v1m/voice/clone", headers=self._headers(False)
            ) as resp:
                if resp.status != 200:
                    log.debug(f"AI33Pro Minimax clones returned status {resp.status}")
                    return
                
                content_type = resp.headers.get("Content-Type", "").lower()
                if "application/json" not in content_type:
                    log.debug(f"AI33Pro Minimax clones returned non-JSON mimetype: {content_type}")
                    return

                data = await resp.json()
        except Exception as e:
            log.warning(f"Failed to fetch Minimax clone voices: {e}")
            return

        clones = data.get("data", []) if isinstance(data, dict) else []
        for v in clones:
            vid = str(v.get("voice_id", ""))
            if not vid:
                continue
            tags = v.get("tag_list") or []
            voices.append(Voice(
                voice_id=vid,
                name=f"{v.get('voice_name', 'Unnamed Clone')} (Clone)",
                provider=self.provider_name,
                language=tags[0] if tags else "Auto",
                gender="unknown",
                preview_url=v.get("sample_audio"),
                metadata={
                    "backend": "minimax",
                    "is_minimax": True,
                    "is_clone": True,
                    "tags": tags,
                },
            ))
            self._minimax_voice_ids.add(vid)

    # ------------------------------------------------------------------
    # clone_voice (Minimax)
    # ------------------------------------------------------------------
    async def clone_voice(
        self,
        name: str,
        audio_path: str | Path,
        description: str = "",
    ) -> Voice:
        """Clone a voice using the Minimax backend."""
        if not self._api_key:
            raise RuntimeError(
                "AI33Pro API Key is not set. Open Settings → API Keys to enter it."
            )

        url = f"{BASE_URL}/v1m/voice/clone"

        data = aiohttp.FormData()
        data.add_field(
            "file", open(audio_path, "rb"),
            filename=Path(audio_path).name, content_type="audio/mpeg",
        )
        data.add_field("voice_name", name)
        data.add_field("preview_text", description or "Hello world, this is a cloned voice sample.")
        data.add_field("language_tag", "English")
        data.add_field("gender_tag", "male")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=self._headers(json_content=False), data=data
            ) as resp:
                result = await resp.json()
                if not result.get("success"):
                    raise RuntimeError(f"Minimax voice cloning failed: {result}")

                voice_id = str(result["cloned_voice_id"])
                log.info(f"Minimax voice cloned successfully: {voice_id}")

                # Make sure subsequent generate() calls route this voice
                # through the Minimax backend without needing a refresh.
                self._minimax_voice_ids.add(voice_id)

                return Voice(
                    voice_id=voice_id,
                    name=f"{name} (Clone)",
                    provider=self.provider_name,
                    metadata={"backend": "minimax", "is_minimax": True, "is_clone": True},
                )
