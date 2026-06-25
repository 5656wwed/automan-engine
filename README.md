# AutoScene Studio

> Cinematic AI Video Generator — Desktop + CLI

AutoScene Studio automatically generates cinematic MP4 videos from sequential images, JSON scene files, and AI-generated voiceovers. Built for content creators, YouTubers, and faceless channel operators.

## Features

- **AI Voiceover Generation** — Inworld, AI33Pro, ElevenLabs, OpenAI, Edge TTS (free), Fish Audio
- **Ken Burns Effects** — Zoom in/out, pan, camera drift
- **Cinematic Transitions** — Random, fade, dissolve, dip-to-black, cross-zoom, cinematic blur
- **Auto Scene Duration** — Matches voiceover length + configurable padding
- **Voice Cloning** — Clone voices from audio samples (ElevenLabs, Fish Audio)
- **Custom Voices** — Add your own Inworld voice IDs via the Settings panel
- **Desktop GUI** — Modern dark-themed interface with drag-and-drop project loading
- **CLI Support** — Full Typer CLI for automation pipelines
- **Production Quality** — H.264/AAC, 1080p/4K, configurable bitrate

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install FFmpeg

Quick install on Windows:
```bash
choco install ffmpeg
# or
scoop install ffmpeg
```

### 3. Configure API Keys

Open the app, go to **Settings**, and paste your API keys. Or copy `.env.example` to `.env` and fill in:

```
ELEVENLABS_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
INWORLD_API_KEY=your_key_here
```

Edge TTS works with no API key (free).

### 4. Launch

**GUI:**
```bash
python app/main.py
```

**CLI:**
```bash
python app/main.py render project.json
```

## Project Structure

Organize each video as a folder:

```
MyProject/
├── project.json
└── images/
    ├── 1.jpg
    ├── 2.jpg
    └── 3.jpg
```

## Project JSON Format

```json
{
  "title": "How a Boy Obsessed With Swallows Became Japan's Most Feared Samurai",
  "aspect_ratio": "16:9",
  "resolution": "1920x1080",
  "fps": 30,
  "transition": "random",
  "transition_duration": 0.5,
  "scenes": [
    {
      "image": "1.jpg",
      "script": "In 1584, a young boy named Miyamoto Musashi was born in a small village in western Japan."
    },
    {
      "image": "2.jpg",
      "script": "Obsessed with swordsmanship from childhood, he fought his first duel at just thirteen years old — and won."
    },
    {
      "image": "3.jpg",
      "script": "By the time he was thirty, Musashi had fought over sixty duels without a single defeat."
    }
  ]
}
```

The output video is saved automatically as `output/<title>.mp4` inside your project folder.

### Scene Fields

| Field | Type | Description |
|-------|------|-------------|
| `image` | string | Image filename — `.jpg`, `.png`, or `.jpeg` |
| `script` | string | Voiceover narration text |
| `transition` | string | Per-scene override: `random`, `fade`, `dissolve`, `cross_zoom`, `dip_to_black`, `cinematic_blur`, `none` |
| `motion` | string | `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `camera_drift`, `none` |
| `duration_padding` | float | Extra seconds after voiceover ends |

### Project-Level Fields

| Field | Default | Description |
|-------|---------|-------------|
| `title` | `"Untitled Project"` | Video title — also used as the output filename |
| `aspect_ratio` | `"16:9"` | `16:9`, `9:16`, or `1:1` |
| `resolution` | `"1920x1080"` | Output resolution |
| `fps` | `30` | Frames per second |
| `transition` | `"random"` | Default transition between all scenes |
| `transition_duration` | `0.5` | Transition length in seconds |

## TTS Providers

| Provider | API Key Required | Notes |
|----------|:---:|---------|
| **Inworld** | ✓ | Premade + custom voices |
| **ElevenLabs** | ✓ | Voice cloning supported |
| **OpenAI** | ✓ | |
| **AI33Pro** | ✓ | ElevenLabs backend |
| **Fish Audio** | ✓ | Custom voice upload |
| **Edge TTS** | ✗ | Free, no key needed |

## CLI Commands

```bash
# Render a project
python app/main.py render project.json

# Render with quality option
python app/main.py render project.json --quality ultra

# Batch render all projects in a folder
python app/main.py batch ./projects/

# List available voices
python app/main.py voices

# List voices from a specific provider
python app/main.py voices --provider inworld

# Check FFmpeg installation
python app/main.py check-ffmpeg
```

## Architecture

```
app/
├── core/        — Config, project model, render pipeline
├── tts/         — TTS providers (Inworld, ElevenLabs, OpenAI, Edge, AI33Pro, Fish Audio)
├── renderer/    — Scene rendering, Ken Burns motion effects
├── transitions/ — Cinematic transitions (FFmpeg xfade)
├── ffmpeg/      — FFmpeg detection and wrapper
├── gui/         — CustomTkinter desktop GUI
├── cli/         — Typer CLI commands
└── utils/       — Audio, caching, logging, validation
```

## Building Executable

```bash
python scripts/build.py
```

Output: `dist/AutoSceneStudio/AutoSceneStudio.exe`

## License

Proprietary — All rights reserved.
