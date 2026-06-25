"""Main rendering pipeline orchestrator."""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Callable, Optional

from app.core.config import ExportSettings, TransitionType, get_config
from app.core.exceptions import RenderError
from app.core.project import Project, load_project
from app.core.timestamps import build_timestamps_content
from app.ffmpeg.detector import detect_ffmpeg
from app.renderer.scene_renderer import SceneRenderer
from app.ffmpeg.wrapper import mix_background_music
from app.transitions.engine import apply_transitions, resolve_transition
from app.tts.voice_manager import VoiceManager
from app.utils.logger import get_logger, setup_logging
from app.utils.validators import find_project_folders

log = get_logger("core.pipeline")


class RenderPipeline:
    """Orchestrates the full video rendering pipeline.

    Pipeline stages:
      1. Validate project
      2. Detect FFmpeg
      3. Generate voiceovers (per-scene TTS)
      4. Render scene clips (image + audio + Ken Burns)
      5. Apply transitions & merge into final video
      6. Export
    """

    def __init__(self, project: Project, export: Optional[ExportSettings] = None):
        self.project = project
        self.export = export or ExportSettings(
            resolution=project.config.resolution,
            fps=project.config.fps,
            quality=project.config.quality or "high",
        )
        self.voice_manager = VoiceManager()
        self.scene_renderer = SceneRenderer(project, self.voice_manager, self.export)

        # Callbacks
        self._on_progress: Optional[Callable[[str, int, int, float], None]] = None
        self._on_log: Optional[Callable[[str], None]] = None
        self._cancelled = False

    def set_progress_callback(
        self,
        callback: Callable[[str, int, int, float], None],
    ) -> None:
        """Set callback: (stage, current_scene, total_scenes, progress_pct)."""
        self._on_progress = callback

    def set_log_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for log messages."""
        self._on_log = callback

    def cancel(self) -> None:
        """Cancel the current render."""
        self._cancelled = True
        log.warning("Render cancelled by user.")

    def _emit_progress(self, stage: str, scene: int, total: int, pct: float):
        if self._on_progress:
            self._on_progress(stage, scene, total, pct)

    async def run(self) -> Path:
        """Execute the full rendering pipeline. Returns path to final video."""
        start_time = time.time()
        self._cancelled = False

        log.info("╔═══════════════════════════════════════════════════╗")
        log.info(f"║  AutoScene Studio — Rendering: {self.project.title}")
        log.info(f"║  Scenes: {self.project.scene_count} | "
                 f"Resolution: {self.export.resolution} | "
                 f"FPS: {self.export.fps}")
        log.info("╚═══════════════════════════════════════════════════╝")

        # ── Stage 1: Validate ────────────────────────────────────────
        self._emit_progress("Validating", 0, self.project.scene_count, 0.0)
        log.info("▸ Stage 1/5: Validating project...")

        errors = self.project.validate()
        if errors:
            for e in errors:
                log.error(f"  ✗ {e}")
            raise RenderError("validation", f"{len(errors)} validation error(s) found.")

        log.info("  ✓ Project validation passed.")

        # ── Stage 2: Detect FFmpeg ───────────────────────────────────
        self._emit_progress("Checking FFmpeg", 0, self.project.scene_count, 0.05)
        log.info("▸ Stage 2/5: Detecting FFmpeg...")

        ffmpeg_info = detect_ffmpeg()
        log.info(f"  ✓ FFmpeg v{ffmpeg_info.version} at {ffmpeg_info.path}")

        # ── Stage 3+4: Render all scenes ─────────────────────────────
        log.info("▸ Stage 3/5: Rendering scenes (TTS + video)...")

        def scene_progress(scene_idx: int, stage: str, pct: float):
            if self._cancelled:
                raise RenderError("cancelled", "Render was cancelled.")
            overall = (scene_idx + pct) / self.project.scene_count
            self._emit_progress(
                f"Scene {scene_idx + 1}: {stage}",
                scene_idx + 1,
                self.project.scene_count,
                0.1 + overall * 0.7,  # Scenes take 10%-80% of total
            )

        clips_with_durations = await self.scene_renderer.render_all_scenes(scene_progress)
        clips = [c[0] for c in clips_with_durations]
        durations = [c[1] for c in clips_with_durations]

        if self._cancelled:
            raise RenderError("cancelled", "Render was cancelled.")

        log.info(f"  ✓ All {len(clips)} scene clips rendered.")

        # ── Stage 4: Transitions & merge ─────────────────────────────
        self._emit_progress("Merging", self.project.scene_count, self.project.scene_count, 0.85)
        log.info("▸ Stage 4/5: Applying transitions & merging...")

        # Resolve per-scene transitions
        transitions = []
        for i in range(len(clips) - 1):
            scene = self.project.scenes[i]
            t = resolve_transition(
                scene_transition=scene.transition,
                project_transition=self.project.config.transition,
            )
            transitions.append(t)

        # Transition duration
        t_dur = self.project.config.transition_duration
        if t_dur is None:
            t_dur = get_config().render.transition_duration

        # Ensure output directory exists
        output_path = self.project.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Auto-pick chapters and write timestamps.txt ──────────────
        # See app/core/timestamps.py for the selection rule. By default
        # the picker chooses ~one chapter per 3 minutes of finished video
        # and derives the chapter label from each chosen scene's script.
        timestamps_body = await build_timestamps_content(
            scenes=self.project.scenes,
            durations=durations,
            transition_duration=t_dur,
        )
        if timestamps_body:
            timestamp_path = output_path.parent / "timestamps.txt"
            timestamp_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp_path.write_text(timestamps_body, encoding="utf-8")
            # Count chapter entries (every line except the "TIMESTAMP:" header)
            chapter_count = max(0, timestamps_body.count("\n"))
            log.info(
                f"  ✓ Timestamps saved ({chapter_count} chapter(s)) → "
                f"{timestamp_path.absolute()}"
            )
        else:
            log.info("  ⚠ No timestamps written (no eligible scenes).")

        final = apply_transitions(
            clip_paths=clips,
            output_path=output_path,
            transition_types=transitions,
            transition_duration=t_dur,
            export=self.export,
        )

        # ── Stage 5: Background Music ────────────────────────────────
        cfg = get_config()
        if cfg.bg_music_enabled:
            _app_root = Path(__file__).resolve().parent.parent.parent
            bg_dir = _app_root / "bg_music"
            music_files = (
                list(bg_dir.glob("*.mp3"))
                + list(bg_dir.glob("*.m4a"))
                + list(bg_dir.glob("*.wav"))
            )
            if music_files:
                chosen = random.choice(music_files)
                log.info(
                    f"▸ Stage 5/5: Mixing background music: {chosen.name} "
                    f"(vol={cfg.bg_music_volume:.0%})"
                )
                self._emit_progress("Mixing BG Music", self.project.scene_count, self.project.scene_count, 0.95)
                bgm_tmp = final.parent / (final.stem + "_bgm_tmp.mp4")
                mix_background_music(final, chosen, bgm_tmp, music_volume=cfg.bg_music_volume, export=self.export)
                import os as _os
                _os.replace(str(bgm_tmp), str(final))
                log.info("  ✓ Background music applied.")
            else:
                log.warning(f"  ⚠ Background music enabled but no files found in {bg_dir}")

        # ── Done ─────────────────────────────────────────────────────
        elapsed = time.time() - start_time
        self._emit_progress("Complete", self.project.scene_count, self.project.scene_count, 1.0)

        log.info("╔═══════════════════════════════════════════════════╗")
        log.info(f"║  ✓ RENDER COMPLETE")
        log.info(f"║  Output : {final}")
        log.info(f"║  Time   : {elapsed:.1f}s")
        log.info("╚═══════════════════════════════════════════════════╝")

        return final


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------
def render_project(json_path: str | Path, **kwargs) -> Path:
    """Synchronous convenience wrapper to render a single project."""
    setup_logging(log_dir=Path(json_path).parent / "logs")
    project = load_project(json_path)
    pipeline = RenderPipeline(project, **kwargs)
    return asyncio.run(pipeline.run())


def batch_render(
    base_dir: str | Path,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> list[dict]:
    """Render all projects found in a directory.

    Returns:
        List of {project, output, success, error} dicts.
    """
    folders = find_project_folders(base_dir)
    results = []

    if not folders:
        log.warning(f"No project folders found in {base_dir}")
        return results

    log.info(f"Batch render: found {len(folders)} projects in {base_dir}")

    for i, folder in enumerate(folders):
        json_file = folder / "project.json"
        project_name = folder.name

        if progress_callback:
            progress_callback(project_name, i + 1, len(folders))

        log.info(f"\n{'═' * 60}")
        log.info(f"Batch [{i + 1}/{len(folders)}]: {project_name}")
        log.info(f"{'═' * 60}")

        try:
            output = render_project(json_file)
            results.append({
                "project": project_name,
                "output": str(output),
                "success": True,
                "error": None,
            })
        except Exception as e:
            log.error(f"Failed to render {project_name}: {e}")
            results.append({
                "project": project_name,
                "output": None,
                "success": False,
                "error": str(e),
            })

    # Summary
    success_count = sum(1 for r in results if r["success"])
    log.info(f"\n{'═' * 60}")
    log.info(f"Batch complete: {success_count}/{len(results)} succeeded")
    log.info(f"{'═' * 60}")

    return results
