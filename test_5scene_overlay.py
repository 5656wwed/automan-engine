"""
test_5scene_overlay.py
5-scene test: 3 scenes with overlay text (typewriter + 1s vanish), 2 plain.
Uses the full app pipeline: load_project -> RenderPipeline -> final video.

Run:
    python test_5scene_overlay.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from app.core.config import load_config, reload_config, ExportSettings, QualityPreset
from app.core.project import load_project
from app.core.pipeline import RenderPipeline


def on_progress(stage: str, scene: int, total: int, pct: float):
    bar = int(pct * 30)
    print(f"\r  [{('#' * bar).ljust(30)}] {pct*100:.0f}%  {stage[:50]:<50}", end="", flush=True)


async def main():
    cfg = load_config()

    if not cfg.inworld_api_key:
        print("ERROR: No Inworld API key in settings. Open the app -> Settings -> Inworld API Key.")
        return

    print(f"Inworld key: {cfg.inworld_api_key[:6]}...")
    print()

    json_path = PROJECT_DIR / "test_5scene_overlay.json"
    project   = load_project(json_path)

    # Check images exist
    missing = project.get_missing_images()
    if missing:
        print(f"ERROR: Missing images: {missing}")
        return

    print(f"Project : {project.title}")
    print(f"Scenes  : {project.scene_count}")
    print(f"Output  : {project.output_path}")
    print()

    # Set Inworld voice — prefer a configured custom voice, otherwise use the
    # known-good default Inworld voice ID from test_patton.py.
    from app.core.project import VoiceConfig
    inworld_voice_id = "default-xtytd8coit3byx-lffsuog__stark"
    if cfg.inworld_custom_voices:
        inworld_voice_id = cfg.inworld_custom_voices[0].get("voice_id", inworld_voice_id)
    project.config.voice = VoiceConfig(
        provider="inworld",
        voice_id=inworld_voice_id,
    )
    print(f"Voice   : inworld / {inworld_voice_id}")
    print()

    export = ExportSettings(
        resolution=project.config.resolution,
        fps=project.config.fps,
        quality=QualityPreset.MEDIUM,  # faster for test
    )

    pipeline = RenderPipeline(project, export=export)
    pipeline.set_progress_callback(on_progress)

    print("Starting render...")
    print("-" * 55)

    output = await pipeline.run()
    print()
    print("-" * 55)
    print(f"Done! Video saved to:")
    print(f"  {output}")


if __name__ == "__main__":
    asyncio.run(main())
