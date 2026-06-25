"""PyInstaller build script for AutoScene Studio."""

import os
import sys
from pathlib import Path

def build():
    """Build Windows .exe using PyInstaller."""
    project_root = Path(__file__).resolve().parent.parent
    main_script = project_root / "app" / "main.py"

    cmd_parts = [
        sys.executable, "-m", "PyInstaller",
        "--name=AutoSceneStudio",
        "--onedir",
        "--windowed",
        "--noconfirm",
    ]
    if (project_root / 'examples').exists():
        cmd_parts.append(f"--add-data={project_root / 'examples'};examples")
    if (project_root / '.env.example').exists():
        cmd_parts.append(f"--add-data={project_root / '.env.example'};.")

    cmd_parts.extend([
        "--hidden-import=customtkinter",
        "--hidden-import=tkinterdnd2",
        "--hidden-import=pydub",
        "--hidden-import=edge_tts",
        "--hidden-import=aiohttp",
        "--hidden-import=pydantic",
        "--hidden-import=app.tts.fish_audio_provider",
        "--hidden-import=app.tts.ai33pro_provider",
        "--hidden-import=app.tts.elevenlabs_provider",
        "--hidden-import=app.tts.openai_provider",
        "--hidden-import=app.tts.edge_provider",
        "--collect-all=customtkinter",
        f"--distpath={project_root / 'dist'}",
        f"--workpath={project_root / 'build'}",
        f"--specpath={project_root / 'build'}",
        str(main_script),
    ])

    cmd = " ".join(cmd_parts)
    print(f"Building AutoScene Studio...")
    print(f"Command: {cmd}\n")
    os.system(cmd)
    print(f"\nBuild complete! Check {project_root / 'dist' / 'AutoSceneStudio'}")


if __name__ == "__main__":
    build()
