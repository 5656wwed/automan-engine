"""Pocket TTS provider — local voice cloning (Kyutai), free, no API key.

Talks to the local Pocket TTS server (default http://127.0.0.1:17494/tts).
Supports:
  - built-in / preset voices via voice_url (e.g. "alba", or an hf:// URL)
  - voice clones: pass a local .safetensors path (uploaded as voice_wav)
Pronunciation cleaning is applied centrally in VoiceManager.generate.
"""

from __future__ import annotations

import array
import os
import struct
from pathlib import Path
from typing import Optional

from app.tts.base import TTSProvider, TTSResult, Voice
from app.utils.logger import get_logger

log = get_logger("tts.pocket")

API_URL = os.environ.get("POCKET_TTS_URL", "http://127.0.0.1:17494/tts")
VOICES_DIR = Path(os.environ.get("POCKET_TTS_VOICES", "/home/ubuntu/pocket_tts_voices"))

# Built-in speaker presets (name -> real speaker audio URL). Subset of the
# Kyutai demo voices; the web UI / voice_id can also be any hf:// URL.
PRESET_VOICE_URLS = {
    "alba": "hf://kyutai/tts-voices/alba-mackenna/casual.wav",
    "cosette": "hf://kyutai/tts-voices/expresso/ex04-ex02_confused_001_channel1_499s.wav",
    "marius": "hf://kyutai/tts-voices/voice-donations/Selfie.wav",
    "javert": "hf://kyutai/tts-voices/voice-donations/Butter.wav",
    "jean": "hf://kyutai/tts-voices/ears/p010/freeform_speech_01_enhanced.wav",
    "george": "hf://kyutai/tts-voices/vctk/p315_023_enhanced.wav",
    "mary": "hf://kyutai/tts-voices/vctk/p333_023_enhanced.wav",
    "michael": "hf://kyutai/tts-voices/vctk/p360_023_enhanced.wav",
}


def _fix_wav_header(data: bytes) -> bytes:
    """Pocket TTS streams WAVs with placeholder sizes; fix so tools can read them."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    if data[36:40] != b"data":
        return data
    out = bytearray(data)
    data_size = len(data) - 44
    struct.pack_into("<I", out, 4, 36 + data_size)
    struct.pack_into("<I", out, 40, data_size)
    return bytes(out)


def _smooth_wav(data: bytes, max_gap_ms: int = 350, thresh: int = 350) -> bytes:
    """Cap long dead-air between sentences so speech feels continuous."""
    if len(data) < 48 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    try:
        channels = struct.unpack_from("<H", data, 22)[0]
        sr = struct.unpack_from("<I", data, 24)[0]
        bits = struct.unpack_from("<H", data, 34)[0]
    except struct.error:
        return data
    if channels != 1 or bits != 16 or sr < 8000:
        return data
    # find data chunk offset
    pos, data_off = 12, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        csize = struct.unpack_from("<I", data, pos + 4)[0]
        if cid == b"data":
            data_off = pos + 8
            break
        pos += 8 + csize
        if csize % 2:
            pos += 1
    if data_off is None:
        return data
    pcm = array.array("h")
    pcm.frombytes(data[data_off:data_off + ((len(data) - data_off) // 2) * 2])
    if not pcm:
        return data
    win = max(1, int(sr * 0.01))
    max_gap = max(1, int(sr * (max_gap_ms / 1000.0)))
    hangover = max(1, int(sr * 0.08))
    fade = max(1, int(sr * 0.006))
    out = array.array("h")
    i, n = 0, len(pcm)
    while i < n:
        speech_start = i
        while i < n:
            end = min(i + win, n)
            chunk = pcm[i:end]
            if (sum(s * s for s in chunk) / len(chunk)) ** 0.5 < thresh:
                break
            i = end
        if i > speech_start:
            out.extend(pcm[speech_start:i])
        if i >= n:
            break
        sil_start = i
        while i < n:
            end = min(i + win, n)
            chunk = pcm[i:end]
            if (sum(s * s for s in chunk) / len(chunk)) ** 0.5 >= thresh:
                break
            i = end
        sil_len = i - sil_start
        keep = min(sil_len, max(max_gap, hangover))
        if keep <= 0:
            continue
        segment = array.array("h", pcm[sil_start:sil_start + keep])
        if keep > hangover + fade:
            for k in range(fade):
                segment[keep - fade + k] = int(segment[keep - fade + k] * ((fade - k) / fade))
        out.extend(segment)
    if not out:
        return data
    body = out.tobytes()
    h = bytearray(44)
    h[0:4] = b"RIFF"; struct.pack_into("<I", h, 4, 36 + len(body))
    h[8:12] = b"WAVE"; h[12:16] = b"fmt "; struct.pack_into("<I", h, 16, 16)
    struct.pack_into("<H", h, 20, 1); struct.pack_into("<H", h, 22, 1)
    struct.pack_into("<I", h, 24, sr); struct.pack_into("<I", h, 28, sr * 2)
    struct.pack_into("<H", h, 32, 2); struct.pack_into("<H", h, 34, 16)
    h[36:40] = b"data"; struct.pack_into("<I", h, 40, len(body))
    return bytes(h) + body


class PocketTTSProvider(TTSProvider):
    provider_name = "pocket"

    def __init__(self, api_url: str = API_URL, voices_dir: Path = VOICES_DIR):
        self.api_url = api_url
        self.voices_dir = Path(voices_dir)

    def _resolve_voice(self, voice_id: str):
        """Return (kind, value): kind in {'url','wav'}."""
        v = voice_id or "alba"
        if v in PRESET_VOICE_URLS:
            return "url", PRESET_VOICE_URLS[v]
        p = Path(v)
        if p.exists() and p.suffix in (".safetensors", ".wav", ".mp3", ".ogg"):
            return "wav", str(p)
        # resolve a bare clone name (stem) against the voices dir
        if self.voices_dir.exists():
            for f in self.voices_dir.glob("*.safetensors"):
                if f.stem.lower() == v.lower():
                    return "wav", str(f)
        if v.startswith(("http://", "https://", "hf://")):
            return "url", v
        return "url", PRESET_VOICE_URLS.get(v, PRESET_VOICE_URLS["alba"])

    def is_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(self.api_url.replace("/tts", "/health"), timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        voice_id: str = "alba",
        speed: float = 1.0,
        pitch: float = 1.0,
        stability: float = 0.5,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        import httpx

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        kind, value = self._resolve_voice(voice_id)

        async with httpx.AsyncClient(timeout=180) as client:
            if kind == "wav":
                with open(value, "rb") as f:
                    files = {"voice_wav": (Path(value).name, f.read(), "application/octet-stream")}
                resp = await client.post(self.api_url, data={"text": text}, files=files)
            else:
                resp = await client.post(
                    self.api_url, data={"text": text, "voice_url": value}
                )
        resp.raise_for_status()

        wav = _smooth_wav(_fix_wav_header(resp.content))
        output_path.write_bytes(wav)

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)
        log.info(f"Generated Pocket TTS audio: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        voices = [Voice(voice_id="alba", name="Alba (built-in)", provider=self.provider_name, language="en")]
        for name in PRESET_VOICE_URLS:
            if name == "alba":
                continue
            voices.append(Voice(voice_id=name, name=name.title(), provider=self.provider_name, language="en"))
        if self.voices_dir.exists():
            for f in sorted(self.voices_dir.glob("*.safetensors")):
                voices.append(Voice(voice_id=str(f), name=f"{f.stem} (clone)", provider=self.provider_name, language="en"))
        return voices
