"""Quick test: overlay text + SFX + TTS voice + Ken Burns on scene 1."""

import asyncio
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(r"C:\Users\leksi\Desktop\NEWYTAUTO")
IMAGE     = PROJECT_DIR / "images" / "1.png"
FONT      = PROJECT_DIR / "font"  / "Tox Typewriter.ttf"
SFX       = PROJECT_DIR / "sfx"   / "whoosh.mp3"
OUTPUT    = PROJECT_DIR / "output" / "test_overlay.mp4"
VOICE_TMP = PROJECT_DIR / "output" / "_test_voice.mp3"

sys.path.insert(0, str(PROJECT_DIR))
from app.ffmpeg.detector import get_ffmpeg_path
ffmpeg = get_ffmpeg_path()

OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# ── 1. Generate TTS voice ─────────────────────────────────────────────────
SCRIPT = "In September 1918, General Edmund Allenby stood opposite three Ottoman armies in Palestine and decided he would not fight them."

async def gen_voice():
    import edge_tts
    # Dramatic documentary voice
    tts = edge_tts.Communicate(SCRIPT, voice="en-US-ChristopherNeural")
    await tts.save(str(VOICE_TMP))

print("Generating voice...")
asyncio.run(gen_voice())
print("Voice done.")

# ── 2. Config ─────────────────────────────────────────────────────────────
OVERLAY_TEXT  = "September 1918"
FONT_SIZE     = 160          # big shout size
TYPE_START    = 0.3          # when typing begins
TOTAL_TYPE    = 2.2          # total seconds for full text to type out
CHAR_DELAY    = TOTAL_TYPE / len(OVERLAY_TEXT)
SFX_DELAY_MS  = int(TYPE_START * 1000)   # SFX fires exactly when text starts
SFX_VOLUME    = 0.55         # audible whoosh
VIDEO_SECONDS = 9
FPS           = 30
TOTAL_FRAMES  = VIDEO_SECONDS * FPS

font_ffmpeg = str(FONT).replace("\\", "/").replace(":", "\\:")

# ── 3. Typewriter drawtext chain ──────────────────────────────────────────
typewriter_filters = []
for i in range(len(OVERLAY_TEXT)):
    t0 = TYPE_START + i * CHAR_DELAY
    t1 = TYPE_START + (i + 1) * CHAR_DELAY
    partial = OVERLAY_TEXT[:i + 1].replace("'", "\\'")
    enable = f"between(t,{t0:.3f},{t1:.3f})" if i < len(OVERLAY_TEXT) - 1 else f"gte(t,{t0:.3f})"
    typewriter_filters.append(
        f"drawtext=fontfile='{font_ffmpeg}'"
        f":text='{partial}'"
        f":fontsize={FONT_SIZE}"
        f":fontcolor=white"
        f":x=80"
        f":y=(h-{FONT_SIZE})/2"
        f":enable='{enable}'"
        f":shadowcolor=black@0.9:shadowx=5:shadowy=5"
    )

# ── 4. Full filter graph ──────────────────────────────────────────────────
# Ken Burns: slow zoom-in from center
ken_burns = (
    f"zoompan=z='min(zoom+0.0012,1.25)'"
    f":d={TOTAL_FRAMES}"
    f":x='iw/2-(iw/zoom/2)'"
    f":y='ih/2-(ih/zoom/2)'"
    f":s=1920x1080:fps={FPS}"
)

video_filter = (
    f"[0:v]scale=3840:2160:force_original_aspect_ratio=decrease,"
    f"pad=3840:2160:(ow-iw)/2:(oh-ih)/2,"
    f"{ken_burns},"
    + ",".join(typewriter_filters)
    + "[v]"
)

audio_filter = (
    f"[1:a]adelay={SFX_DELAY_MS}|{SFX_DELAY_MS},volume={SFX_VOLUME}[sfx];"
    f"[2:a]adelay=300|300[voice];"
    f"[sfx][voice]amix=inputs=2:duration=longest,"
    f"apad=whole_dur={VIDEO_SECONDS}[a]"
)

filter_complex = video_filter + ";" + audio_filter

cmd = [
    ffmpeg, "-y", "-hide_banner",
    "-loop", "1", "-i", str(IMAGE),
    "-i", str(SFX),
    "-i", str(VOICE_TMP),
    "-filter_complex", filter_complex,
    "-map", "[v]",
    "-map", "[a]",
    "-t", str(VIDEO_SECONDS),
    "-r", str(FPS),
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    "-pix_fmt", "yuv420p",
    str(OUTPUT),
]

print("Running FFmpeg (Ken Burns + typewriter + voice)...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

if result.returncode == 0:
    print(f"Done! Open: {OUTPUT}")
else:
    print("FFmpeg error:")
    print(result.stderr[-3000:])
