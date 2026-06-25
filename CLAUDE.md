# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Launch GUI (no args)
python app/main.py

# CLI render
python app/main.py render project.json
python app/main.py render project.json --quality ultra

# Batch render all projects in a folder
python app/main.py batch ./projects/

# List voices
python app/main.py voices --provider inworld

# Run tests
pytest

# Install dependencies
pip install -r requirements.txt
```

FFmpeg binaries are bundled in `.tools/ffmpeg/bin/`. `app/ffmpeg/detector.py` finds them automatically; no system FFmpeg needed.

## Architecture

**Entry point**: `app/main.py` — launches GUI if no CLI args, CLI otherwise. Adds project root to `sys.path` and patches pydub with the bundled FFmpeg path.

**Config**: `app/core/config.py` — `AppConfig` Pydantic model, singleton via `get_config()` / `reload_config()`. API keys and settings are persisted to `%APPDATA%/AutoSceneStudio/settings.json` (never to `.env`). The `.env` file only supports `FFMPEG_PATH`.

**Project model**: `app/core/project.py` — `ProjectConfig` (Pydantic) loaded from `project.json`. `Project` wraps it with resolved image paths and computed properties. Output goes to `<project_dir>/<title_slug>/` where `title_slug` is the first 3 words of the title, joined with underscores.

**Render pipeline** (`app/core/pipeline.py`): `RenderPipeline` runs 5 stages: validate → detect FFmpeg → render scenes (TTS + video) → apply transitions → export. The `run()` method is async; the GUI drives it from a thread via `asyncio.run_coroutine_threadsafe`.

**Scene rendering** (`app/renderer/scene_renderer.py`): `SceneRenderer` processes one scene at a time: generate TTS audio → add silence padding → measure duration → FFmpeg `image_to_video` (Ken Burns + drawtext overlay) → FFmpeg `add_audio_to_video`. Completed clips are identified by a 12-char MD5 cache key and skipped on re-render.

**FFmpeg wrapper** (`app/ffmpeg/wrapper.py`): All FFmpeg calls go through `_run_ffmpeg(args_list)` using `subprocess.Popen` with list args and `CREATE_NO_WINDOW` on Windows — no shell. Never build FFmpeg commands as strings.

**TTS providers** (`app/tts/`): All implement `TTSProvider` base class from `app/tts/base.py`. Unified through `VoiceManager`. Inworld is always registered (premade voices browsable without a key); other paid providers only register when their API key is set. The `generate()` call raises if a key is missing at synthesis time.

**GUI** (`app/gui/`): CustomTkinter with a sidebar + 5 content frames (Project, Voices, Render, Settings, Logs). All frames are instantiated at startup and `tkraise()`d to switch. The Render frame drives `RenderPipeline` in a background thread and pumps progress back via `after()`.

## Key invariants

**FFmpeg drawtext escaping** (`scene_renderer._escape_drawtext_text`): The entire `text=` value is wrapped in a single pair of single-quotes (`'...'`). Inside single-quotes, colons (`:`) are NOT treated as literal characters by FFmpeg (they are still parsed as option separators) and therefore MUST be escaped as `\\:`. Also, `\\` → `\\\\` and `'` → `'\''` must be escaped. Unicode dashes (`–`, `—`, `−`) must be normalised to ASCII `-` first — they corrupt as multi-byte sequences on Windows. Do NOT revert to splitting on `:` and joining with `\\:` between quoted segments: FFmpeg's option parser treats the closing `'` of the first segment as the end of the entire value, leaving `\\:''` to be parsed as an option name, which breaks the whole filter chain.

**`overlay_text` in project.json**: Keep to 3 words or fewer. Use only ASCII letters, numbers, spaces, and hyphens. Use K/M shorthand for large numbers (`25K-40K`). No colons, commas, or Unicode punctuation.

**Scene cache key**: Encodes provider + voice_id + script + TTS params + image filename + motion + resolution + overlay_text. Changing any of these forces a re-render of that scene.

**Audio timing**: `scene_duration = get_audio_duration(padded_audio)`. The raw video is rendered to exactly this duration (`-t scene_duration`). The `add_audio_to_video` step uses `-shortest`. When SFX is present (`sfx/whoosh.mp3` exists in the project dir), voice audio is delayed 200 ms via `adelay`; the default `duration_padding` of 0.5 s absorbs this.

**Motion resolution order**: scene-level `motion` field → project-level `motion` field → weighted-random (seeded by scene index for reproducibility).

**Transitions**: Applied between clips by `app/transitions/engine.py` using FFmpeg `xfade`. Stream-copy concat is used when all transitions are `none`.
