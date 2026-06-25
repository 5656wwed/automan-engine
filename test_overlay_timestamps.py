"""
test_overlay_timestamps.py
3-scene test: Inworld TTS WORD timestamps - overlay fires at exact spoken moment.

Output: output/test_timestamps/scene_1.mp4, scene_2.mp4, scene_3.mp4
"""

import asyncio
import base64
import subprocess
import sys
from pathlib import Path

import aiohttp

PROJECT_DIR = Path(r"C:\Users\leksi\Desktop\NEWYTAUTO")
sys.path.insert(0, str(PROJECT_DIR))

from app.core.config import load_config
from app.ffmpeg.detector import get_ffmpeg_path, get_ffprobe_path
from app.utils.audio import get_audio_duration

ffmpeg  = get_ffmpeg_path()
ffprobe = get_ffprobe_path()

FONT       = PROJECT_DIR / "font" / "Tox Typewriter.ttf"
SFX        = PROJECT_DIR / "sfx"  / "whoosh.mp3"
OUTPUT_DIR = PROJECT_DIR / "output" / "test_timestamps"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

font_ffmpeg = str(FONT).replace("\\", "/").replace(":", "\\:")

# ── Scenes ────────────────────────────────────────────────────────────────────
SCENES = [
    {
        "image"       : PROJECT_DIR / "images" / "1.png",
        "script"      : "In September 1918, General Edmund Allenby stood opposite three Ottoman armies in Palestine.",
        "overlay_text": "September 1918",
    },
    {
        "image"       : PROJECT_DIR / "images" / "2.png",
        "script"      : "He commanded the most powerful cavalry force in the entire Middle East.",
        "overlay_text": "Middle East",
    },
    {
        "image"       : PROJECT_DIR / "images" / "3.png",
        "script"      : "His plan was to destroy three armies in a single week.",
        "overlay_text": "Three Armies",
    },
]

# ── Global overlay settings ───────────────────────────────────────────────────
VOICE_ID    = "default-xtytd8coit3byx-lffsuog__stark"
FONT_SIZE   = 130
TOTAL_TYPE  = 2.0    # seconds for full overlay to finish typing
SFX_VOLUME  = 0.55
FPS         = 30
PADDING     = 0.8    # silence after voice ends

INWORLD_URL   = "https://api.inworld.ai/tts/v1/voice"
INWORLD_MODEL = "inworld-tts-2"


# ── Step 1: Inworld TTS with WORD timestamps ──────────────────────────────────
async def generate_tts(text: str, output_path: Path, api_key: str) -> dict:
    """Call Inworld TTS with timestampAlignment=WORD. Returns timestampInfo dict."""
    payload = {
        "text"       : text,
        "voiceId"    : VOICE_ID,
        "modelId"    : INWORLD_MODEL,
        "audioConfig": {
            "audioEncoding"  : "MP3",
            "sampleRateHertz": 22050,
            "speakingRate"   : 1.0,
        },
        "deliveryMode"        : "BALANCED",
        "applyTextNormalization": "ON",
        "timestampType"       : "WORD",
    }
    headers = {
        "Authorization": f"Basic {api_key}",
        "Content-Type" : "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(INWORLD_URL, headers=headers, json=payload) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"Inworld {resp.status}: {data.get('message', data)}")

            audio_b64 = data.get("audioContent")
            if not audio_b64:
                raise RuntimeError(f"No audioContent: {data}")

            output_path.write_bytes(base64.b64decode(audio_b64))
            print(f"    Audio saved: {output_path.name}")
            return data.get("timestampInfo", {})


# ── Step 2: Find exact spoken timestamp ──────────────────────────────────────
def find_overlay_start(timestamp_info: dict, overlay_text: str) -> float:
    """Find the second when the first word of overlay_text is spoken."""
    wa = timestamp_info.get("wordAlignment", {})
    words      = wa.get("words", [])
    starts     = wa.get("wordStartTimeSeconds", [])

    if not words or not starts:
        print("    [!] No word timestamps in response - falling back to 0.3s")
        return 0.3

    # Print all words so we can see what Inworld returned
    pairs = [(w, f"{t:.2f}s") for w, t in zip(words, starts)]
    print(f"    Words: {pairs}")

    target = overlay_text.split()[0].lower().rstrip(".,!?;:")

    # Skip spaces and empty tokens — Inworld returns them as separate entries
    real_words = [(w, t) for w, t in zip(words, starts) if w.strip()]

    # Exact match
    for word, t in real_words:
        if word.lower().rstrip(".,!?;:") == target:
            print(f"    [ok] '{target}' found at {t:.3f}s")
            return t

    # Partial match (handles number normalisation like "35,000" -> "thirty")
    for word, t in real_words:
        if target in word.lower():
            print(f"    [~] partial '{word}' at {t:.3f}s")
            return t

    print(f"    [!] '{target}' not found - falling back to 0.3s")
    return 0.3


# ── Step 3: FFmpeg render ─────────────────────────────────────────────────────
def render_scene(
    image       : Path,
    audio       : Path,
    output      : Path,
    overlay_text: str,
    overlay_start: float,
    duration    : float,
) -> bool:
    total_frames = int(duration * FPS)
    char_delay   = TOTAL_TYPE / max(len(overlay_text), 1)
    sfx_delay_ms = int(overlay_start * 1000)

    # Build typewriter drawtext chain
    typewriter = []
    for i in range(len(overlay_text)):
        t0      = overlay_start + i * char_delay
        t1      = overlay_start + (i + 1) * char_delay
        partial = overlay_text[:i + 1].replace("'", "\\'").replace(":", "\\:")
        enable  = (
            f"between(t,{t0:.3f},{t1:.3f})"
            if i < len(overlay_text) - 1
            else f"gte(t,{t0:.3f})"
        )
        typewriter.append(
            f"drawtext=fontfile='{font_ffmpeg}'"
            f":text='{partial}'"
            f":fontsize={FONT_SIZE}"
            f":fontcolor=white"
            f":x=80"
            f":y=(h-{FONT_SIZE})/2"
            f":enable='{enable}'"
            f":shadowcolor=black@0.9:shadowx=4:shadowy=4"
        )

    ken_burns = (
        f"zoompan=z='min(zoom+0.0010,1.20)'"
        f":d={total_frames}"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)'"
        f":s=1920x1080:fps={FPS}"
    )

    vf = (
        f"[0:v]scale=3840:2160:force_original_aspect_ratio=decrease,"
        f"pad=3840:2160:(ow-iw)/2:(oh-ih)/2,"
        f"{ken_burns},"
        + ",".join(typewriter)
        + "[v]"
    )

    af = (
        f"[2:a]adelay={sfx_delay_ms}|{sfx_delay_ms},volume={SFX_VOLUME}[sfx];"
        f"[1:a]adelay=200|200[voice];"
        f"[sfx][voice]amix=inputs=2:duration=longest,"
        f"apad=whole_dur={duration:.2f}[a]"
    )

    cmd = [
        ffmpeg, "-y", "-hide_banner",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        "-i", str(SFX),
        "-filter_complex", vf + ";" + af,
        "-map", "[v]", "-map", "[a]",
        "-t", str(duration),
        "-r", str(FPS),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        str(output),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode == 0:
        print(f"    [ok] Rendered: {output.name}")
        return True
    print(f"    [!] FFmpeg error:\n{res.stderr[-2000:]}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    cfg = load_config()
    api_key = cfg.inworld_api_key
    if not api_key:
        print("[!] No Inworld API key. Open Settings -> API Keys and save it first.")
        return

    print(f"Inworld key loaded ({api_key[:6]}...)\n")

    clips = []
    for idx, scene in enumerate(SCENES, 1):
        print(f"{'-'*55}")
        print(f"Scene {idx}/3  overlay='{scene['overlay_text']}'")

        audio_out  = OUTPUT_DIR / f"scene_{idx}_voice.mp3"
        video_out  = OUTPUT_DIR / f"scene_{idx}.mp4"

        # 1. TTS + timestamps
        print("  [1] Generating TTS...")
        ts_info = await generate_tts(scene["script"], audio_out, api_key)

        # 2. Find overlay start
        print("  [2] Locating overlay word...")
        overlay_start = find_overlay_start(ts_info, scene["overlay_text"])

        # 3. Scene duration
        voice_dur     = get_audio_duration(audio_out)
        scene_dur     = voice_dur + PADDING
        print(f"  [3] Duration: {voice_dur:.1f}s voice + {PADDING}s pad = {scene_dur:.1f}s")

        # 4. Render
        print("  [4] Rendering video...")
        ok = render_scene(
            image        = scene["image"],
            audio        = audio_out,
            output       = video_out,
            overlay_text = scene["overlay_text"],
            overlay_start= overlay_start,
            duration     = scene_dur,
        )
        if ok:
            clips.append(video_out)

    print(f"\n{'='*55}")
    print(f"Done: {len(clips)}/3 scenes rendered.")
    for c in clips:
        print(f"  {c}")
    if len(clips) < 3:
        print("[!] Check errors above.")


if __name__ == "__main__":
    asyncio.run(main())
