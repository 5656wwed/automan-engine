import subprocess
import sys
from pathlib import Path

# Paths
ffmpeg_path = r"C:\Users\leksi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.EXE"
image_path = r"C:\Users\leksi\Desktop\NEWYTAUTO\images\004.png"
output_path = r"C:\Users\leksi\Desktop\NEWYTAUTO\The_Australian_Soldier\.tmp\35854c7c32\test_scene_004.mp4"
font_path = r"C:\Users\leksi\Desktop\NEWYTAUTO\font\Tox Typewriter.ttf"

# Let's mock the filter chain
# Width/Height
width, height = 1920, 1080
canvas_w, canvas_h = width * 2, height * 2
total_frames = 399 # 13.3s * 30fps

# Base scale
base_scale = f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,crop={canvas_w}:{canvas_h}"

# Motion (ZOOM_IN)
zoom_expr = f"zoompan=z='min(1.0+0.08*on/{total_frames},1.08)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"

# Font path formatting for FFmpeg
font_ffmpeg = font_path.replace("\\", "/").replace(":", "\\:")

# Drawtext filter for "Kokoda Trail" (len 12)
overlay_text = "Kokoda Trail"
char_delay = 2.0 / len(overlay_text)
overlay_start = 0.3
vanish_at = overlay_start + 2.0 + 1.0

drawtext_filters = []
for i in range(len(overlay_text)):
    t0 = overlay_start + i * char_delay
    t1 = overlay_start + (i + 1) * char_delay
    partial = overlay_text[:i + 1]
    # Simple escaping
    partial_escaped = f"'{partial}'"
    enable = f"between(t,{t0:.3f},{t1:.3f})" if i < len(overlay_text) - 1 else f"between(t,{t0:.3f},{vanish_at:.3f})"
    drawtext_filters.append(
        f"drawtext=fontfile='{font_ffmpeg}':text={partial_escaped}:fontsize=130:fontcolor=white:x=80:y=(h-130)/2:enable='{enable}':shadowcolor=black@0.9:shadowx=4:shadowy=4"
    )

filter_str = ",".join([base_scale, zoom_expr] + drawtext_filters)

cmd = [
    ffmpeg_path, "-y", "-hide_banner",
    "-loop", "1",
    "-i", image_path,
    "-vf", filter_str,
    "-t", "13.3",
    "-c:v", "libx264",
    "-crf", "18",
    "-preset", "slow",
    "-pix_fmt", "yuv420p",
    "-r", "30",
    output_path
]

print("Running command...")
try:
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    print("Process finished with code:", res.returncode)
    print("STDOUT:", res.stdout)
    print("STDERR last 50 lines:")
    print("\n".join(res.stderr.splitlines()[-50:]))
except subprocess.TimeoutExpired as e:
    print("TIMEOUT EXPIRED!")
    print("STDOUT:", e.stdout)
    print("STDERR last 50 lines of stderr captured:")
    if e.stderr:
        print("\n".join(e.stderr.splitlines()[-50:]))
    else:
        print("No stderr captured (or was not piped correctly).")
