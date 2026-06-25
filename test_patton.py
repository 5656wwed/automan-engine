"""
test_patton.py
5-scene sample: Patton project.json overlay feature test.
- Scenes with overlay_text get typewriter animation timed to the exact spoken word
- Scenes with null overlay render normally (voice + Ken Burns only)
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
from app.ffmpeg.detector import get_ffmpeg_path
from app.utils.audio import get_audio_duration

ffmpeg     = get_ffmpeg_path()
FONT       = PROJECT_DIR / "font" / "Tox Typewriter.ttf"
SFX        = PROJECT_DIR / "sfx"  / "whoosh.mp3"
OUTPUT_DIR = PROJECT_DIR / "output" / "test_patton"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

font_ffmpeg = str(FONT).replace("\\", "/").replace(":", "\\:")

# ── First 5 scenes ────────────────────────────────────────────────────────────
SCENES = [
    {
        "image"       : "1.png",
        "script"      : "Spring, 1944. Behind Allied lines.",
        "overlay_text": "Spring 1944",
    },
    {
        "image"       : "2.png",
        "script"      : "A German officer sits with his arms folded and his chin raised.",
        "overlay_text": None,
    },
    {
        "image"       : "3.png",
        "script"      : "Every man in the room has stood. The American officers. The orderlies. The interpreters.",
        "overlay_text": None,
    },
    {
        "image"       : "4.png",
        "script"      : "All of them snapped to attention the moment General George S. Patton walked through the door.",
        "overlay_text": "General Patton",
    },
    {
        "image"       : "5.png",
        "script"      : "The German sits alone.",
        "overlay_text": None,
    },
]

# ── Settings ──────────────────────────────────────────────────────────────────
VOICE_ID      = "default-xtytd8coit3byx-lffsuog__stark"
FONT_SIZE     = 130
TOTAL_TYPE    = 2.0
SFX_VOLUME    = 0.55
FPS           = 30
PADDING       = 0.8
INWORLD_URL   = "https://api.inworld.ai/tts/v1/voice"
INWORLD_MODEL = "inworld-tts-2"


# ── TTS ───────────────────────────────────────────────────────────────────────
async def generate_tts(text: str, output_path: Path, api_key: str, want_timestamps: bool) -> dict:
    payload = {
        "text"        : text,
        "voiceId"     : VOICE_ID,
        "modelId"     : INWORLD_MODEL,
        "audioConfig" : {"audioEncoding": "MP3", "sampleRateHertz": 22050, "speakingRate": 1.0},
        "deliveryMode": "BALANCED",
        "applyTextNormalization": "ON",
    }
    if want_timestamps:
        payload["timestampType"] = "WORD"

    headers = {"Authorization": f"Basic {api_key}", "Content-Type": "application/json"}
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
            return data.get("timestampInfo", {})


# ── Find spoken timestamp ─────────────────────────────────────────────────────
def find_overlay_start(timestamp_info: dict, overlay_text: str) -> float:
    wa     = timestamp_info.get("wordAlignment", {})
    words  = wa.get("words", [])
    starts = wa.get("wordStartTimeSeconds", [])

    if not words or not starts:
        print("    [!] No timestamps — using 0.3s fallback")
        return 0.3

    real = [(w, t) for w, t in zip(words, starts) if w.strip()]
    target = overlay_text.split()[0].lower().rstrip(".,!?;:")

    for word, t in real:
        if word.lower().rstrip(".,!?;:") == target:
            print(f"    [ok] '{target}' spoken at {t:.3f}s")
            return t

    for word, t in real:
        if target in word.lower():
            print(f"    [~] partial '{word}' at {t:.3f}s")
            return t

    print(f"    [!] '{target}' not found — using 0.3s fallback")
    return 0.3


# ── FFmpeg render (with overlay) ──────────────────────────────────────────────
def render_with_overlay(image: Path, audio: Path, output: Path,
                         overlay_text: str, overlay_start: float, duration: float) -> bool:
    total_frames = int(duration * FPS)
    char_delay   = TOTAL_TYPE / max(len(overlay_text), 1)
    sfx_ms       = int(overlay_start * 1000)

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
            f":x=80:y=(h-{FONT_SIZE})/2"
            f":enable='{enable}'"
            f":shadowcolor=black@0.9:shadowx=4:shadowy=4"
        )

    ken_burns = (
        f"zoompan=z='min(zoom+0.0010,1.20)':d={total_frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={FPS}"
    )

    vf = (
        f"[0:v]scale=3840:2160:force_original_aspect_ratio=decrease,"
        f"pad=3840:2160:(ow-iw)/2:(oh-ih)/2,{ken_burns},"
        + ",".join(typewriter) + "[v]"
    )
    af = (
        f"[2:a]adelay={sfx_ms}|{sfx_ms},volume={SFX_VOLUME}[sfx];"
        f"[1:a]adelay=200|200[voice];"
        f"[sfx][voice]amix=inputs=2:duration=longest,apad=whole_dur={duration:.2f}[a]"
    )

    cmd = [
        ffmpeg, "-y", "-hide_banner",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        "-i", str(SFX),
        "-filter_complex", vf + ";" + af,
        "-map", "[v]", "-map", "[a]",
        "-t", str(duration), "-r", str(FPS),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        str(output),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode == 0:
        print(f"    [ok] Rendered with overlay: {output.name}")
        return True
    print(f"    [!] FFmpeg error:\n{res.stderr[-2000:]}")
    return False


# ── FFmpeg render (no overlay) ────────────────────────────────────────────────
def render_plain(image: Path, audio: Path, output: Path, duration: float) -> bool:
    total_frames = int(duration * FPS)
    ken_burns = (
        f"zoompan=z='min(zoom+0.0010,1.20)':d={total_frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={FPS}"
    )
    vf = (
        f"[0:v]scale=3840:2160:force_original_aspect_ratio=decrease,"
        f"pad=3840:2160:(ow-iw)/2:(oh-ih)/2,{ken_burns}[v]"
    )
    af = "[1:a]adelay=200|200,apad=whole_dur={:.2f}[a]".format(duration)

    cmd = [
        ffmpeg, "-y", "-hide_banner",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        "-filter_complex", vf + ";" + af,
        "-map", "[v]", "-map", "[a]",
        "-t", str(duration), "-r", str(FPS),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        str(output),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode == 0:
        print(f"    [ok] Rendered plain: {output.name}")
        return True
    print(f"    [!] FFmpeg error:\n{res.stderr[-2000:]}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    cfg = load_config()
    api_key = cfg.inworld_api_key
    if not api_key:
        print("[!] No Inworld API key found.")
        return

    print(f"Inworld key loaded ({api_key[:6]}...)\n")

    clips = []
    for idx, scene in enumerate(SCENES, 1):
        overlay = scene["overlay_text"]
        # treat string "null" same as None
        if isinstance(overlay, str) and overlay.lower() == "null":
            overlay = None

        has_overlay = overlay is not None
        print(f"{'-'*55}")
        print(f"Scene {idx}/5  overlay={repr(overlay)}")

        image_path = PROJECT_DIR / "images" / scene["image"]
        audio_path = OUTPUT_DIR / f"scene_{idx}_voice.mp3"
        video_path = OUTPUT_DIR / f"scene_{idx}.mp4"

        # TTS — request timestamps only when we need them
        print("  [1] Generating TTS...")
        ts_info = await generate_tts(scene["script"], audio_path, api_key, want_timestamps=has_overlay)

        # Duration
        voice_dur  = get_audio_duration(audio_path)
        scene_dur  = voice_dur + PADDING
        print(f"  [2] Duration: {voice_dur:.1f}s + {PADDING}s pad = {scene_dur:.1f}s")

        # Render
        print("  [3] Rendering...")
        if has_overlay:
            overlay_start = find_overlay_start(ts_info, overlay)
            ok = render_with_overlay(image_path, audio_path, video_path,
                                     overlay, overlay_start, scene_dur)
        else:
            ok = render_plain(image_path, audio_path, video_path, scene_dur)

        if ok:
            clips.append(video_path)

    print(f"\n{'='*55}")
    print(f"Done: {len(clips)}/5 scenes rendered.")
    for c in clips:
        print(f"  {c}")


if __name__ == "__main__":
    asyncio.run(main())
