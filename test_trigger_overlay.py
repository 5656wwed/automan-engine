"""
test_trigger_overlay.py
Tests rendering of project_trigger_test.json with custom trigger list overlays.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(r"C:\Users\leksi\Desktop\NEWYTAUTO")
sys.path.insert(0, str(PROJECT_DIR))

# Ensure stdout/stderr handles UTF-8 correctly on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def test_render():
    print("Starting render of project_trigger_test.json...")
    
    # Run the main.py CLI render command with UTF-8 env variable
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    cmd = [
        sys.executable,
        str(PROJECT_DIR / "app" / "main.py"),
        "render",
        str(PROJECT_DIR / "project_trigger_test.json"),
        "--quality",
        "low"
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, env=env, encoding="utf-8")
    
    print("\n--- STDOUT ---")
    print(result.stdout)
    
    print("\n--- STDERR ---")
    print(result.stderr)
    
    if result.returncode != 0:
        print(f"[!] Render failed with exit code {result.returncode}")
        sys.exit(result.returncode)
        
    print("[ok] Render completed successfully!")
    
    # Check if final output video exists
    output_dir = PROJECT_DIR / "output" / "Trigger_Overlay_Feature"
    output_video = output_dir / "trigger_test_output.mp4"
    
    if output_video.exists():
        print(f"[ok] Output video exists: {output_video}")
        print(f"Size: {output_video.stat().st_size} bytes")
    else:
        print(f"[!] Output video not found in expected path: {output_video}")
        for f in output_dir.rglob("*.mp4"):
            print(f"Found other mp4: {f}")
        sys.exit(1)

if __name__ == "__main__":
    test_render()
