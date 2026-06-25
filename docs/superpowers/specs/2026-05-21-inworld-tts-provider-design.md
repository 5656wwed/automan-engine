# Inworld TTS Provider — Design Spec

**Date:** 2026-05-21  
**Status:** Approved

---

## Overview

Add Inworld AI as a TTS provider in AutoScene Studio. The provider supports both Inworld's built-in premade voices and user-configured custom voices (identified by a voice ID and a display name). Custom voices are persisted in the app's `settings.json` via `AppConfig`.

---

## 1. New Provider — `app/tts/inworld_provider.py`

Subclasses `TTSProvider`. Uses `aiohttp` (already a dependency) for HTTP — no SDK.

### `__init__(api_key, custom_voices)`
- `api_key: Optional[str]` — Inworld Basic auth key
- `custom_voices: list[dict]` — list of `{"id": str, "name": str}` dicts loaded from config

### `is_available() -> bool`
Returns `True` if `api_key` is non-empty and not a placeholder string.

### `generate(text, output_path, voice_id, speed, stability, **kwargs) -> TTSResult`
- **Endpoint:** `POST https://api.inworld.ai/tts/v1/voice`
- **Auth:** `Authorization: Basic {api_key}`
- **Request body:**
  ```json
  {
    "text": "<text>",
    "voiceId": "<voice_id>",
    "modelId": "inworld-tts-2",
    "audioConfig": {
      "audioEncoding": "MP3",
      "sampleRateHertz": 22050,
      "speakingRate": <speed>
    },
    "deliveryMode": "<mapped from stability>",
    "applyTextNormalization": "ON"
  }
  ```
- **`deliveryMode` mapping** (from `stability` 0.0–1.0):
  - `< 0.33` → `STABLE`
  - `< 0.66` → `BALANCED`
  - `≥ 0.66` → `CREATIVE`
- **Response:** JSON with `audioContent` (base64-encoded MP3 bytes). Decode and write to `output_path`.
- **Error handling:** Non-200 responses raise `TTSError("inworld", message, scene_index)`.
- Returns `TTSResult(audio_path, duration, voice_id, text)`.

### `list_voices() -> list[Voice]`
Returns two groups concatenated:
1. **Hardcoded premade voices** — a static list of known Inworld built-in voices (e.g. Dennis, Rachel, Adam, etc.)
2. **User custom voices** — built from `self._custom_voices`, each entry mapped to `Voice(voice_id=d["id"], name=d["name"], provider="inworld", metadata={"custom": True})`

Custom voices are sorted to the top (same convention as FishAudioProvider).

---

## 2. Config Changes — `app/core/config.py`

### `TTSProvider` enum
```python
INWORLD = "inworld"
```

### `AppConfig`
```python
inworld_api_key: Optional[str] = None
inworld_custom_voices: list[dict] = Field(default_factory=list)
```
Each dict in `inworld_custom_voices` has shape `{"id": str, "name": str}`.

---

## 3. VoiceManager — `app/tts/voice_manager.py`

### `_init_providers()`
```python
from app.tts.inworld_provider import InworldProvider

inworld = InworldProvider(
    api_key=config.inworld_api_key,
    custom_voices=config.inworld_custom_voices,
)
if inworld.is_available():
    self._providers["inworld"] = inworld
```

### `get_provider()` error messages
Add `"inworld": "Inworld API Key not configured. Please set it in Settings."` to the helpful error dict.

---

## 4. Settings UI — `app/gui/frames/settings_frame.py`

### API Key row
Add to `API_KEY_FIELDS`:
```python
("inworld_key", "Inworld API Key", "inworld_api_key"),
```

### Inworld Custom Voices panel
A new `CTkFrame` card rendered below the API keys card, only relevant to Inworld. Contains:

**Header:** "🎙 Inworld Custom Voices"

**Voice list:** A scrollable area listing each saved custom voice as one row:
- Format: `{name}  —  {voice_id}`
- A `✕` delete button on each row. Clicking removes the entry from `inworld_custom_voices`, saves config, and refreshes the list.

**Add form:** Two `CTkEntry` fields side by side:
- "Voice Name" (display name)
- "Voice ID" (Inworld voice ID)
- `＋ Add` button: validates both fields non-empty, appends `{"id": ..., "name": ...}` to `config.inworld_custom_voices`, saves, refreshes the list and clears the entries.

State is persisted via the existing `save_config()` / `reload_config()` flow.

---

## 5. What Is Not In Scope

- Streaming TTS endpoint (`/tts/v1/voice/stream`) — not needed; the sync endpoint is sufficient for AutoScene's use case.
- Timestamp alignment (`timestampType`) — not used by the renderer.
- Voice cloning via Inworld — Inworld does not expose a cloning API in the provided docs; custom voices are user-managed externally and referenced by ID.

---

## Files Changed

| File | Change |
|------|--------|
| `app/tts/inworld_provider.py` | **New** |
| `app/core/config.py` | Add enum value + two fields |
| `app/tts/voice_manager.py` | Register new provider |
| `app/gui/frames/settings_frame.py` | Add API key row + custom voice panel |
