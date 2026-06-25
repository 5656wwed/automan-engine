# Inworld TTS Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Inworld AI as a TTS provider supporting both hardcoded premade voices and user-managed custom voices stored in `settings.json`.

**Architecture:** New `InworldProvider` follows the existing `TTSProvider` ABC pattern, using `aiohttp` for REST calls (same as `FishAudioProvider`). Config gets two new fields (`inworld_api_key`, `inworld_custom_voices`). The Settings UI gains an API key row and a custom voice manager panel. No SDK — pure HTTP.

**Tech Stack:** Python 3.10+, `aiohttp`, `base64` (stdlib), `customtkinter`, `pydantic`, `pytest`, `pytest-asyncio`

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/tts/inworld_provider.py` | `InworldProvider` class |
| Create | `tests/__init__.py` | Test package marker |
| Create | `tests/test_inworld_provider.py` | Unit tests |
| Create | `pytest.ini` | asyncio_mode config |
| Modify | `app/core/config.py` | Add enum value + two `AppConfig` fields |
| Modify | `app/tts/voice_manager.py` | Register `InworldProvider` |
| Modify | `app/gui/frames/settings_frame.py` | API key row + custom voice panel |
| Modify | `requirements.txt` | Add `pytest`, `pytest-asyncio` |

---

## Task 1: Config Changes

**Files:**
- Modify: `app/core/config.py`

- [ ] **Step 1: Add `INWORLD` to `TTSProvider` enum**

In `app/core/config.py`, find the `TTSProvider` enum and add the new value:

```python
class TTSProvider(str, Enum):
    ELEVENLABS = "elevenlabs"
    OPENAI = "openai"
    EDGE = "edge"
    AI33PRO = "ai33pro"
    FISHAUDIO = "fishaudio"
    INWORLD = "inworld"          # ← add this line
```

- [ ] **Step 2: Add two fields to `AppConfig`**

Find `AppConfig` and add after `fish_audio_api_key`:

```python
class AppConfig(BaseModel):
    # API Keys
    elevenlabs_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    ai33pro_api_key: Optional[str] = None
    fish_audio_api_key: Optional[str] = None
    inworld_api_key: Optional[str] = None                              # ← add
    inworld_custom_voices: list[dict] = Field(default_factory=list)   # ← add
    ...
```

`Field` is already imported from pydantic at the top of the file.

- [ ] **Step 3: Commit**

```bash
git add app/core/config.py
git commit -m "feat: add inworld_api_key and inworld_custom_voices to AppConfig"
```

---

## Task 2: Add Test Infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `pytest.ini`
- Create: `tests/__init__.py`

- [ ] **Step 1: Add test deps to requirements.txt**

Append to the end of `requirements.txt`:

```
# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Install them**

```bash
pip install pytest pytest-asyncio
```

Expected: both packages install without error.

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 4: Create `tests/__init__.py`**

Empty file — just touch it:

```python
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini tests/__init__.py
git commit -m "chore: add pytest and pytest-asyncio for testing"
```

---

## Task 3: Write Failing Tests for InworldProvider

**Files:**
- Create: `tests/test_inworld_provider.py`

- [ ] **Step 1: Write the full test file**

Create `tests/test_inworld_provider.py`:

```python
"""Tests for InworldProvider."""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tts.inworld_provider import (
    INWORLD_PREMADE_VOICES,
    InworldProvider,
    _stability_to_delivery_mode,
)
from app.core.exceptions import TTSError


# ── helpers ──────────────────────────────────────────────────────────

def _make_aiohttp_mock(status: int, json_data: dict):
    """Build a mock for aiohttp.ClientSession as an async context manager.

    Hierarchy:
      aiohttp.ClientSession(...)  → session_cm  (async ctx)
        session_cm.__aenter__()  → mock_session
        mock_session.post(...)   → post_cm      (async ctx)
          post_cm.__aenter__()   → mock_resp
    """
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)

    post_cm = AsyncMock()
    post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    post_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=post_cm)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    return session_cm, mock_session


# ── is_available ─────────────────────────────────────────────────────

def test_is_available_with_key():
    assert InworldProvider(api_key="test-key").is_available() is True


def test_is_available_without_key():
    assert InworldProvider().is_available() is False


def test_is_available_empty_string():
    assert InworldProvider(api_key="").is_available() is False


def test_is_available_whitespace():
    assert InworldProvider(api_key="   ").is_available() is False


# ── _stability_to_delivery_mode ───────────────────────────────────────

def test_delivery_mode_stable_low():
    assert _stability_to_delivery_mode(0.0) == "STABLE"


def test_delivery_mode_stable_high():
    assert _stability_to_delivery_mode(0.32) == "STABLE"


def test_delivery_mode_balanced_low():
    assert _stability_to_delivery_mode(0.33) == "BALANCED"


def test_delivery_mode_balanced_mid():
    assert _stability_to_delivery_mode(0.5) == "BALANCED"


def test_delivery_mode_balanced_high():
    assert _stability_to_delivery_mode(0.65) == "BALANCED"


def test_delivery_mode_creative_boundary():
    assert _stability_to_delivery_mode(0.66) == "CREATIVE"


def test_delivery_mode_creative_max():
    assert _stability_to_delivery_mode(1.0) == "CREATIVE"


# ── list_voices ───────────────────────────────────────────────────────

async def test_list_voices_no_custom():
    provider = InworldProvider(api_key="key")
    voices = await provider.list_voices()
    assert len(voices) == len(INWORLD_PREMADE_VOICES)
    voice_ids = [v.voice_id for v in voices]
    for vid, _name, _gender in INWORLD_PREMADE_VOICES:
        assert vid in voice_ids


async def test_list_voices_custom_comes_first():
    custom = [{"id": "my-voice-001", "name": "Studio Voice"}]
    provider = InworldProvider(api_key="key", custom_voices=custom)
    voices = await provider.list_voices()

    assert voices[0].voice_id == "my-voice-001"
    assert voices[0].name == "Studio Voice"
    assert voices[0].metadata["custom"] is True
    assert len(voices) == len(INWORLD_PREMADE_VOICES) + 1


async def test_list_voices_multiple_custom():
    custom = [
        {"id": "voice-a", "name": "Voice A"},
        {"id": "voice-b", "name": "Voice B"},
    ]
    provider = InworldProvider(api_key="key", custom_voices=custom)
    voices = await provider.list_voices()
    assert voices[0].voice_id == "voice-a"
    assert voices[1].voice_id == "voice-b"
    assert len(voices) == len(INWORLD_PREMADE_VOICES) + 2


async def test_list_voices_premade_not_marked_custom():
    provider = InworldProvider(api_key="key")
    voices = await provider.list_voices()
    for v in voices:
        assert v.metadata.get("custom") is False


# ── generate ─────────────────────────────────────────────────────────

async def test_generate_writes_audio_file(tmp_path):
    raw_audio = b"FAKE_MP3_DATA"
    encoded = base64.b64encode(raw_audio).decode()
    session_cm, mock_session = _make_aiohttp_mock(
        200, {"audioContent": encoded, "usage": {"processedCharactersCount": 11}}
    )
    output = tmp_path / "out.mp3"

    with patch("aiohttp.ClientSession", return_value=session_cm):
        with patch("app.utils.audio.get_audio_duration", return_value=1.5):
            provider = InworldProvider(api_key="test-key")
            result = await provider.generate(
                text="Hello world",
                output_path=output,
                voice_id="Dennis",
                speed=1.0,
                stability=0.5,
            )

    assert output.exists()
    assert output.read_bytes() == raw_audio
    assert result.voice_id == "Dennis"
    assert result.duration == 1.5
    assert result.text == "Hello world"


async def test_generate_sends_correct_payload(tmp_path):
    encoded = base64.b64encode(b"audio").decode()
    session_cm, mock_session = _make_aiohttp_mock(200, {"audioContent": encoded})
    output = tmp_path / "out.mp3"

    with patch("aiohttp.ClientSession", return_value=session_cm):
        with patch("app.utils.audio.get_audio_duration", return_value=1.0):
            provider = InworldProvider(api_key="my-api-key")
            await provider.generate(
                text="Test narration",
                output_path=output,
                voice_id="Rachel",
                speed=0.9,
                stability=0.2,  # → STABLE
            )

    call_kwargs = mock_session.post.call_args
    assert call_kwargs[0][0] == "https://api.inworld.ai/tts/v1/voice"
    sent_json = call_kwargs[1]["json"]
    assert sent_json["text"] == "Test narration"
    assert sent_json["voiceId"] == "Rachel"
    assert sent_json["modelId"] == "inworld-tts-2"
    assert sent_json["audioConfig"]["speakingRate"] == 0.9
    assert sent_json["audioConfig"]["audioEncoding"] == "MP3"
    assert sent_json["deliveryMode"] == "STABLE"
    assert sent_json["applyTextNormalization"] == "ON"


async def test_generate_auth_header(tmp_path):
    encoded = base64.b64encode(b"audio").decode()
    session_cm, mock_session = _make_aiohttp_mock(200, {"audioContent": encoded})
    output = tmp_path / "out.mp3"

    with patch("aiohttp.ClientSession", return_value=session_cm):
        with patch("app.utils.audio.get_audio_duration", return_value=1.0):
            provider = InworldProvider(api_key="my-secret-key")
            await provider.generate("text", output, voice_id="Dennis")

    headers = mock_session.post.call_args[1]["headers"]
    assert headers["Authorization"] == "Basic my-secret-key"


async def test_generate_raises_tts_error_on_failure(tmp_path):
    session_cm, _ = _make_aiohttp_mock(
        400, {"code": 5, "message": "Unknown voice: Bogus not found!", "details": []}
    )
    output = tmp_path / "out.mp3"

    with patch("aiohttp.ClientSession", return_value=session_cm):
        provider = InworldProvider(api_key="key")
        with pytest.raises(TTSError) as exc_info:
            await provider.generate("text", output, voice_id="Bogus")

    assert "Bogus not found" in str(exc_info.value)


async def test_generate_raises_when_no_api_key(tmp_path):
    provider = InworldProvider()
    with pytest.raises(TTSError):
        await provider.generate("text", tmp_path / "out.mp3", voice_id="Dennis")
```

- [ ] **Step 2: Run tests — expect import failures**

```bash
pytest tests/test_inworld_provider.py -v
```

Expected output includes: `ModuleNotFoundError: No module named 'app.tts.inworld_provider'`

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_inworld_provider.py pytest.ini
git commit -m "test: add failing tests for InworldProvider (TDD)"
```

---

## Task 4: Implement InworldProvider

**Files:**
- Create: `app/tts/inworld_provider.py`

- [ ] **Step 1: Create the provider file**

Create `app/tts/inworld_provider.py`:

```python
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

# Premade voices available on Inworld AI (Dennis confirmed from API docs)
INWORLD_PREMADE_VOICES: list[tuple[str, str, str]] = [
    ("Dennis", "Dennis", "male"),
    ("Rachel", "Rachel", "female"),
    ("Adam", "Adam", "male"),
    ("Bella", "Bella", "female"),
    ("Josh", "Josh", "male"),
    ("Aria", "Aria", "female"),
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

        model_id = kwargs.get("model_id", DEFAULT_MODEL)
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

                audio_bytes = base64.b64decode(data["audioContent"])
                output_path.write_bytes(audio_bytes)

        from app.utils.audio import get_audio_duration
        duration = get_audio_duration(output_path)

        log.info(f"Generated Inworld audio: {output_path.name} ({duration:.1f}s)")

        return TTSResult(
            audio_path=output_path,
            duration=duration,
            voice_id=voice_id,
            text=text,
        )

    async def list_voices(self) -> list[Voice]:
        custom = [
            Voice(
                voice_id=v["id"],
                name=v["name"],
                provider=self.provider_name,
                metadata={"custom": True},
            )
            for v in self._custom_voices
        ]
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
        return custom + premade
```

- [ ] **Step 2: Run tests — all should pass**

```bash
pytest tests/test_inworld_provider.py -v
```

Expected: all tests `PASSED`. If any fail, fix before continuing.

- [ ] **Step 3: Commit**

```bash
git add app/tts/inworld_provider.py
git commit -m "feat: add InworldProvider TTS integration"
```

---

## Task 5: Register Provider in VoiceManager

**Files:**
- Modify: `app/tts/voice_manager.py`

- [ ] **Step 1: Add import**

At the top of `app/tts/voice_manager.py`, after the existing imports, add:

```python
from app.tts.inworld_provider import InworldProvider
```

- [ ] **Step 2: Register in `_init_providers()`**

Inside `_init_providers()`, after the Fish Audio block, add:

```python
inworld = InworldProvider(
    api_key=config.inworld_api_key,
    custom_voices=config.inworld_custom_voices,
)
if inworld.is_available():
    self._providers["inworld"] = inworld
```

- [ ] **Step 3: Add helpful error message**

In `get_provider()`, find the `errors` dict and add:

```python
errors = {
    "ai33pro": "AI33Pro API Key not configured. Please set it in Settings.",
    "elevenlabs": "ElevenLabs API Key not configured. Please set it in Settings.",
    "openai": "OpenAI API Key not configured. Please set it in Settings.",
    "inworld": "Inworld API Key not configured. Please set it in Settings.",  # ← add
}
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests still pass.

- [ ] **Step 5: Commit**

```bash
git add app/tts/voice_manager.py
git commit -m "feat: register InworldProvider in VoiceManager"
```

---

## Task 6: Settings UI — API Key Row

**Files:**
- Modify: `app/gui/frames/settings_frame.py`

- [ ] **Step 1: Add Inworld to `API_KEY_FIELDS`**

Find the `API_KEY_FIELDS` list at the top of `settings_frame.py` and add the Inworld entry:

```python
API_KEY_FIELDS = [
    ("elevenlabs_key", "ElevenLabs API Key", "elevenlabs_api_key"),
    ("openai_key",     "OpenAI API Key",     "openai_api_key"),
    ("ai33pro_key",    "AI33Pro API Key",    "ai33pro_api_key"),
    ("fishaudio_key",  "Fish Audio API Key",  "fish_audio_api_key"),
    ("inworld_key",    "Inworld API Key",     "inworld_api_key"),   # ← add
]
```

No other changes needed — `_build_api_key_row`, `_load_state`, and `_persist_keys_from_ui` all iterate over `API_KEY_FIELDS` automatically.

- [ ] **Step 2: Commit**

```bash
git add app/gui/frames/settings_frame.py
git commit -m "feat: add Inworld API key row to Settings UI"
```

---

## Task 7: Settings UI — Custom Voices Panel

**Files:**
- Modify: `app/gui/frames/settings_frame.py`

- [ ] **Step 1: Add `_build_inworld_custom_voices_card()` method**

Add this method to the `SettingsFrame` class (after `_build_api_key_row`):

```python
def _build_inworld_custom_voices_card(self, parent) -> None:
    """Build the Inworld custom voices management card."""
    card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
    card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

    ctk.CTkLabel(
        card, text="🎙 Inworld Custom Voices",
        font=FONTS["heading_sm"], text_color=COLORS["text_primary"], anchor="w",
    ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

    ctk.CTkLabel(
        card,
        text="Add your custom Inworld voice IDs here. They appear at the top of the voice list.",
        font=FONTS["body_sm"], text_color=COLORS["text_muted"],
        anchor="w", justify="left", wraplength=720,
    ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))

    # Scrollable list area for existing custom voices
    self._inworld_voice_list_frame = ctk.CTkFrame(card, fg_color="transparent")
    self._inworld_voice_list_frame.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"]))

    # Add form row
    add_row = ctk.CTkFrame(card, fg_color="transparent")
    add_row.pack(fill="x", padx=SPACING["md"], pady=(SPACING["xs"], SPACING["md"]))

    self._inworld_name_entry = ctk.CTkEntry(
        add_row, placeholder_text="Display name",
        fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
        border_color=COLORS["border"], border_width=1, corner_radius=8, height=34,
    )
    self._inworld_name_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

    self._inworld_id_entry = ctk.CTkEntry(
        add_row, placeholder_text="Voice ID",
        fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
        border_color=COLORS["border"], border_width=1, corner_radius=8, height=34,
    )
    self._inworld_id_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

    ctk.CTkButton(
        add_row, text="＋ Add", font=FONTS["body_sm"],
        fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
        text_color="white", corner_radius=8, height=34, width=80,
        command=self._add_inworld_custom_voice,
    ).pack(side="right")

    self._refresh_inworld_voice_list()
```

- [ ] **Step 2: Add `_refresh_inworld_voice_list()` method**

```python
def _refresh_inworld_voice_list(self) -> None:
    """Clear and rebuild the list of saved custom Inworld voices."""
    for widget in self._inworld_voice_list_frame.winfo_children():
        widget.destroy()

    config = get_config()
    voices = config.inworld_custom_voices or []

    if not voices:
        ctk.CTkLabel(
            self._inworld_voice_list_frame,
            text="No custom voices added yet.",
            font=FONTS["body_sm"], text_color=COLORS["text_muted"], anchor="w",
        ).pack(fill="x")
        return

    for i, voice in enumerate(voices):
        row = ctk.CTkFrame(self._inworld_voice_list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)

        ctk.CTkLabel(
            row,
            text=f"{voice.get('name', '?')}  —  {voice.get('id', '?')}",
            font=FONTS["body_sm"], text_color=COLORS["text_secondary"], anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            row, text="✕", font=FONTS["body_sm"],
            fg_color="transparent", text_color=COLORS["error"],
            hover_color="#2d1a1a", corner_radius=6, height=26, width=32,
            command=lambda idx=i: self._delete_inworld_custom_voice(idx),
        ).pack(side="right")
```

- [ ] **Step 3: Add `_add_inworld_custom_voice()` method**

```python
def _add_inworld_custom_voice(self) -> None:
    """Validate entries, persist new custom voice, refresh list."""
    name = self._inworld_name_entry.get().strip()
    voice_id = self._inworld_id_entry.get().strip()

    if not name or not voice_id:
        return  # both fields required; entries highlight placeholder as hint

    config = get_config()
    voices = list(config.inworld_custom_voices or [])
    voices.append({"id": voice_id, "name": name})
    config.inworld_custom_voices = voices
    save_config(config)
    reload_config()

    self._inworld_name_entry.delete(0, "end")
    self._inworld_id_entry.delete(0, "end")
    self._refresh_inworld_voice_list()
    self._refresh_voice_frame()
```

- [ ] **Step 4: Add `_delete_inworld_custom_voice()` method**

```python
def _delete_inworld_custom_voice(self, index: int) -> None:
    """Remove custom voice at given index, persist, refresh list."""
    config = get_config()
    voices = list(config.inworld_custom_voices or [])
    if 0 <= index < len(voices):
        voices.pop(index)
        config.inworld_custom_voices = voices
        save_config(config)
        reload_config()
        self._refresh_inworld_voice_list()
        self._refresh_voice_frame()
```

- [ ] **Step 5: Call `_build_inworld_custom_voices_card()` from `_build_ui()`**

In `_build_ui()`, after the existing API keys card is built (after the `btn_row` section), add a call to the new method. Find the line that creates `ffmpeg_card` and insert above it:

```python
        # --- Inworld Custom Voices section ---
        self._build_inworld_custom_voices_card(scroll)

        # --- FFmpeg section ---
        ffmpeg_card = ctk.CTkFrame(scroll, ...)
```

- [ ] **Step 6: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/gui/frames/settings_frame.py
git commit -m "feat: add Inworld custom voice manager panel to Settings UI"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `InworldProvider` with `generate()`, `list_voices()`, `is_available()` — Task 4
- ✅ `Authorization: Basic {api_key}` header — Task 4, Step 1 (`_headers()`)
- ✅ `deliveryMode` mapped from stability — Task 4, `_stability_to_delivery_mode()`
- ✅ `INWORLD` enum value — Task 1
- ✅ `inworld_api_key` field on `AppConfig` — Task 1
- ✅ `inworld_custom_voices: list[dict]` with `Field(default_factory=list)` — Task 1
- ✅ VoiceManager registers provider + helpful error — Task 5
- ✅ API key row in Settings — Task 6
- ✅ Custom voices panel (add + delete + list) — Task 7
- ✅ Custom voices appear first in `list_voices()` — Task 4

**Placeholder scan:** No TBDs, no "implement later", no incomplete steps.

**Type consistency:**
- `_custom_voices: list[dict]` in provider matches `inworld_custom_voices: list[dict]` in config — ✅
- `TTSError("inworld", message)` matches `TTSError(provider, message)` signature in `exceptions.py` — ✅
- `Voice(voice_id, name, provider, gender, metadata)` fields match `base.py` dataclass — ✅
- `save_config` / `reload_config` / `get_config` all imported already in `settings_frame.py` — ✅
