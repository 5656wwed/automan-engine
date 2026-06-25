import asyncio
import sys
from pathlib import Path

# Insert project directory to path
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from app.core.project import load_project, VoiceConfig
from app.core.pipeline import RenderPipeline
from app.core.config import ExportSettings, AspectRatio

async def main():
    # Disable background music mixing for the tests to prevent file locking and make it faster
    from app.core.config import get_config
    get_config().bg_music_enabled = False

    print("Loading project...")
    project_path = PROJECT_DIR / "project.json"
    if not project_path.exists():
        print(f"Error: {project_path} does not exist.")
        return
        
    project = load_project(project_path)
    
    # Pre-clean output paths to release locks
    output_dir = project.project_output_dir
    if output_dir.exists():
        for f in ["test_subtitles_9_16.mp4", "test_subtitles_16_9.mp4", "test_subtitles_16_9_bgm_tmp.mp4", "test_subtitles_9_16_bgm_tmp.mp4"]:
            p = output_dir / f
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
    
    # Configure project for testing subtitles in 9:16
    project.config.subtitles_enabled = True
    project.config.subtitles_style = "auto"
    project.config.aspect_ratio = "9:16"
    project.config.resolution = "1080x1920"
    
    # Ensure it uses Edge TTS provider so it is free and has no API key requirement
    if not project.config.voice:
        project.config.voice = VoiceConfig()
    project.config.voice.provider = "edge"
    project.config.voice.voice_id = "en-US-ChristopherNeural"
    
    # Render only the first scene to make it fast
    project.config.scenes = project.config.scenes[:1]

    
    # Set output name
    project.config.output = "test_subtitles_9_16.mp4"
    
    export = ExportSettings(
        aspect_ratio=AspectRatio.PORTRAIT,
        resolution="1080x1920",
        fps=30,
        quality="low"  # low quality makes the test render extremely fast
    )
    
    print("Initializing pipeline for 9:16 test...")
    pipeline = None
    try:
        pipeline = RenderPipeline(project, export=export)
        print("Running render for 9:16 subtitles...")
        out_path = await pipeline.run()
        print(f"[SUCCESS] 9:16 Subtitle Render complete! Output saved to: {out_path.absolute()}")
    except Exception as e:
        print(f"[ERROR] 9:16 Subtitle Render failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Now let's test 16:9 normal subtitles
    print("\nLoading project for 16:9 test...")
    try:
        project_16_9 = load_project(project_path)
        project_16_9.config.subtitles_enabled = True
        project_16_9.config.subtitles_style = "normal"
        project_16_9.config.aspect_ratio = "16:9"
        project_16_9.config.resolution = "1920x1080"
        if not project_16_9.config.voice:
            project_16_9.config.voice = VoiceConfig()
        project_16_9.config.voice.provider = "edge"
        project_16_9.config.voice.voice_id = "en-US-ChristopherNeural"
        project_16_9.config.scenes = project_16_9.config.scenes[:1]
        project_16_9.config.output = "test_subtitles_16_9.mp4"
        
        export_16_9 = ExportSettings(
            aspect_ratio=AspectRatio.LANDSCAPE,
            resolution="1920x1080",
            fps=30,
            quality="low"
        )
        
        print("Initializing pipeline for 16:9 test...")
        pipeline_16_9 = RenderPipeline(project_16_9, export=export_16_9)
        print("Running render for 16:9 subtitles...")
        out_path_16_9 = await pipeline_16_9.run()
        print(f"[SUCCESS] 16:9 Subtitle Render complete! Output saved to: {out_path_16_9.absolute()}")
    except Exception as e:
        print(f"[ERROR] 16:9 Subtitle Render failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
