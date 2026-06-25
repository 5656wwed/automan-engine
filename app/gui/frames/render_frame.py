"""Render frame — render controls, progress bar, export settings."""

from __future__ import annotations

import asyncio
import datetime
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from app.core.config import ExportSettings, QualityPreset, AspectRatio
from app.core.pipeline import RenderPipeline
from app.core.project import Project, VoiceConfig
from app.gui.components.progress_bar import RenderProgressBar
from app.gui.theme import COLORS, FONTS, SPACING
from app.utils.logger import register_gui_callback, unregister_gui_callback


class RenderFrame(ctk.CTkFrame):
    """Render controls, progress tracking, and export settings."""

    def __init__(self, master, app_ref=None, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], corner_radius=0, **kwargs)
        self.app_ref = app_ref
        self._project: Optional[Project] = None
        self._pipeline: Optional[RenderPipeline] = None
        self._rendering = False

        self._build_ui()
        register_gui_callback(self._on_log_record)
        self.bind("<Destroy>", lambda _: unregister_gui_callback(self._on_log_record))

    def _build_ui(self):
        # Header
        ctk.CTkLabel(
            self, text="🎬 Render", font=FONTS["heading_lg"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        # Export settings card
        settings_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        settings_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            settings_card, text="Export Settings", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["sm"]))

        # Settings grid
        grid = ctk.CTkFrame(settings_card, fg_color="transparent")
        grid.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Aspect Ratio
        ctk.CTkLabel(grid, text="Aspect Ratio", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w", padx=SPACING["xs"])
        self._ratio_var = ctk.StringVar(value="16:9")
        self._ratio_menu = ctk.CTkOptionMenu(
            grid, variable=self._ratio_var,
            values=["16:9", "9:16", "1:1"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=120,
            command=self._on_ratio_changed,
        )
        self._ratio_menu.grid(row=1, column=0, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Resolution
        ctk.CTkLabel(grid, text="Resolution", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=0, column=1, sticky="w", padx=SPACING["xs"])
        self._resolution_var = ctk.StringVar(value="1920x1080")
        self._res_menu = ctk.CTkOptionMenu(
            grid, variable=self._resolution_var,
            values=["1920x1080", "1280x720", "3840x2160"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=150,
        )
        self._res_menu.grid(row=1, column=1, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # FPS
        ctk.CTkLabel(grid, text="FPS", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=0, column=2, sticky="w", padx=SPACING["xs"])
        self._fps_var = ctk.StringVar(value="30")
        ctk.CTkOptionMenu(
            grid, variable=self._fps_var,
            values=["24", "25", "30", "60"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=80,
        ).grid(row=1, column=2, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Quality
        ctk.CTkLabel(grid, text="Quality", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=0, column=3, sticky="w", padx=SPACING["xs"])
        self._quality_var = ctk.StringVar(value="high")
        ctk.CTkOptionMenu(
            grid, variable=self._quality_var,
            values=["low", "medium", "high", "ultra"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=100,
        ).grid(row=1, column=3, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Transition
        ctk.CTkLabel(grid, text="Transition", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=2, column=0, sticky="w", padx=SPACING["xs"], pady=(SPACING["sm"], 0))
        self._transition_var = ctk.StringVar(value="random")
        ctk.CTkOptionMenu(
            grid, variable=self._transition_var,
            values=["random", "fade", "dissolve", "cross_zoom", "dip_to_black", "cinematic_blur", "none"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=160,
        ).grid(row=3, column=0, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Transition Duration
        ctk.CTkLabel(grid, text="Transition Duration (s)", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=2, column=1, sticky="w", padx=SPACING["xs"], pady=(SPACING["sm"], 0))
        self._transition_dur_var = ctk.StringVar(value="0.5")
        self._transition_dur_menu = ctk.CTkOptionMenu(
            grid, variable=self._transition_dur_var,
            values=["0.3", "0.5", "0.8", "1.0", "1.5", "2.0"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=120,
        )
        self._transition_dur_menu.grid(row=3, column=1, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Subtitles (On/Off)
        ctk.CTkLabel(grid, text="Subtitles", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=2, column=2, sticky="w", padx=SPACING["xs"], pady=(SPACING["sm"], 0))
        self._subtitles_enabled_var = ctk.StringVar(value="Disabled")
        self._subtitles_enabled_menu = ctk.CTkOptionMenu(
            grid, variable=self._subtitles_enabled_var,
            values=["Disabled", "Enabled"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=100,
        )
        self._subtitles_enabled_menu.grid(row=3, column=2, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Subtitle Style
        ctk.CTkLabel(grid, text="Subtitle Style", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=2, column=3, sticky="w", padx=SPACING["xs"], pady=(SPACING["sm"], 0))
        self._subtitles_style_var = ctk.StringVar(value="auto")
        self._subtitles_style_menu = ctk.CTkOptionMenu(
            grid, variable=self._subtitles_style_var,
            values=["auto", "word_by_word", "normal"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=140,
        )
        self._subtitles_style_menu.grid(row=3, column=3, sticky="w", padx=SPACING["xs"], pady=SPACING["xs"])

        # Output path
        output_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        output_frame.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            output_frame, text="Output", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        out_row = ctk.CTkFrame(output_frame, fg_color="transparent")
        out_row.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))

        self._output_var = ctk.StringVar(value="output/final_video.mp4")
        self._output_entry = ctk.CTkEntry(
            out_row, textvariable=self._output_var,
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8, height=36,
        )
        self._output_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

        ctk.CTkButton(
            out_row, text="Browse", font=FONTS["body_sm"],
            fg_color=COLORS["bg_medium"], hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"], corner_radius=6, height=36, width=80,
            command=self._browse_output,
        ).pack(side="right")

        # Progress section
        progress_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        progress_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            progress_card, text="Progress", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["sm"]))

        self._progress_bar = RenderProgressBar(progress_card, total_scenes=1)
        self._progress_bar.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))

        # Render button area
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=SPACING["lg"], pady=SPACING["md"])
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=0)

        self._render_btn = ctk.CTkButton(
            btn_frame,
            text="🚀  Start Render",
            font=("Segoe UI", 18, "bold"),
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_dark"],
            text_color="white",
            corner_radius=12,
            height=56,
            command=self._toggle_render,
        )
        self._render_btn.grid(row=0, column=0, sticky="ew")

        self._resume_btn = ctk.CTkButton(
            btn_frame,
            text="Resume",
            font=("Segoe UI", 14, "bold"),
            fg_color=COLORS["bg_medium"],
            hover_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"],
            corner_radius=12,
            height=56,
            width=110,
            command=self._resume_render,
        )
        self._resume_btn.grid(row=0, column=1, sticky="ew", padx=(SPACING["xs"], 0))
        self._resume_btn.grid_remove()  # hidden until error / cancel

        # Status
        self._status = ctk.CTkLabel(
            self, text="Load a project to begin", font=FONTS["body"],
            text_color=COLORS["text_muted"], anchor="w",
        )
        self._status.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        # Log panel
        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=SPACING["lg"], pady=(SPACING["sm"], 0))

        ctk.CTkLabel(
            log_header, text="Log", font=FONTS["heading_sm"],
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            log_header, text="Clear", font=FONTS["body_sm"],
            fg_color="transparent", text_color=COLORS["text_muted"],
            hover_color=COLORS["bg_medium"], corner_radius=6, height=24, width=50,
            command=self._clear_log,
        ).pack(side="right")

        self._log_box = ctk.CTkTextbox(
            self, height=160,
            fg_color=COLORS["bg_card"],
            text_color=COLORS["text_secondary"],
            font=("Consolas", 11),
            corner_radius=8,
            wrap="word",
            state="disabled",
        )
        self._log_box.pack(fill="x", padx=SPACING["lg"], pady=(0, SPACING["md"]))

        # Color tags for log levels
        self._log_box.tag_config("ERROR",   foreground="#f87171")
        self._log_box.tag_config("WARNING", foreground="#fbbf24")
        self._log_box.tag_config("INFO",    foreground=COLORS["text_secondary"])
        self._log_box.tag_config("DEBUG",   foreground=COLORS["text_muted"])

    @staticmethod
    def _title_to_filename(title: str) -> str:
        import re
        safe = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        safe = re.sub(r"\s+", " ", safe)
        return safe or "output"

    def set_project(self, project: Project):
        """Called when a project is loaded."""
        self._project = project
        self._progress_bar.set_total(project.scene_count)
        self._progress_bar.reset()
        filename = self._title_to_filename(project.title) + ".mp4"
        self._output_var.set(str(project.project_output_dir / filename))
        self._ratio_var.set(project.config.aspect_ratio or "16:9")
        self._on_ratio_changed(self._ratio_var.get())
        self._resolution_var.set(project.config.resolution)
        self._fps_var.set(str(project.config.fps))
        if project.config.transition:
            self._transition_var.set(project.config.transition)
        if project.config.transition_duration is not None:
            self._transition_dur_var.set(str(project.config.transition_duration))
        self._subtitles_enabled_var.set("Enabled" if getattr(project.config, "subtitles_enabled", False) else "Disabled")
        self._subtitles_style_var.set(getattr(project.config, "subtitles_style", "auto") or "auto")
        self._status.configure(
            text=f"Ready to render: {project.title} ({project.scene_count} scenes)",
            text_color=COLORS["success"],
        )

    def _on_ratio_changed(self, ratio: str):
        """Update resolution options when aspect ratio changes."""
        options = {
            "16:9": ["1920x1080", "1280x720", "3840x2160"],
            "9:16": ["1080x1920", "720x1280", "2160x3840"],
            "1:1":  ["1080x1080", "720x720", "1440x1440"],
        }
        res_list = options.get(ratio, ["1920x1080"])
        self._res_menu.configure(values=res_list)
        
        # Auto-select the first one if current resolution doesn't match ratio
        current = self._resolution_var.get()
        if current not in res_list:
            self._resolution_var.set(res_list[0])

    def _browse_output(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4")],
        )
        if path:
            self._output_var.set(path)

    # ------------------------------------------------------------------
    # Log panel
    # ------------------------------------------------------------------
    def _on_log_record(self, level: str, module: str, message: str) -> None:
        """Receive a log record from GUIHandler and append it to the log box."""
        self.after(0, lambda: self._append_log(level, message))

    def _append_log(self, level: str, message: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", message + "\n", level)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def log_error(self, message: str) -> None:
        """Write a plain error line directly to the log box (for render errors)."""
        self._append_log("ERROR", f"ERROR: {message}")

    def _toggle_render(self):
        if self._rendering:
            self._cancel_render()
        else:
            self._resume_btn.grid_remove()
            self._start_render()

    def _resume_render(self):
        """Re-run the pipeline — already-rendered scenes are skipped via cache."""
        self._resume_btn.grid_remove()
        self.log_error("--- Resuming render ---")
        self._start_render()

    def _start_render(self):
        if not self._project:
            self._status.configure(text="⚠ No project loaded!", text_color=COLORS["warning"])
            return

        self._rendering = True
        self._render_start_time = datetime.datetime.now()
        self._render_btn.configure(text="⏹  Cancel Render", fg_color=COLORS["error"])
        self._progress_bar.reset()

        # Build export settings
        export = ExportSettings(
            aspect_ratio=AspectRatio(self._ratio_var.get()),
            resolution=self._resolution_var.get(),
            fps=int(self._fps_var.get()),
            quality=QualityPreset(self._quality_var.get()),
        )

        # Override output path and aspect ratio in project
        self._project.config.output = self._output_var.get()
        self._project.config.aspect_ratio = self._ratio_var.get()
        self._project.config.resolution = self._resolution_var.get()
        self._project.config.transition = self._transition_var.get()
        self._project.config.transition_duration = float(self._transition_dur_var.get())
        self._project.config.subtitles_enabled = (self._subtitles_enabled_var.get() == "Enabled")
        self._project.config.subtitles_style = self._subtitles_style_var.get()

        # ── Pull voice selection from the Voices tab and apply it ────────
        # at the project level. Per-scene voice overrides in the JSON
        # still win (see scene_renderer.py), but for every scene that
        # doesn't specify one, we use what the user picked in the GUI.
        self._apply_voice_selection_to_project()

        self._pipeline = RenderPipeline(self._project, export=export)

        def on_progress(stage, scene, total, pct):
            self.after(0, lambda: self._progress_bar.update_progress(stage, scene, total, pct))
            self.after(0, lambda: self._status.configure(text=stage, text_color=COLORS["accent_primary"]))

        self._pipeline.set_progress_callback(on_progress)

        def _run():
            try:
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(self._pipeline.run())
                loop.close()
                self.after(0, lambda: self._on_render_complete(result))
            except Exception as e:
                import traceback as _tb
                tb_str = _tb.format_exc()
                self.after(0, lambda err=e, tb=tb_str: self._on_render_error(err, tb))

        threading.Thread(target=_run, daemon=True).start()

    def _apply_voice_selection_to_project(self) -> None:
        """Copy the voice picker's current state into ``project.config.voice``.

        This is what makes the voice the user picked in the Voices tab
        actually take effect at render time. Without it the pipeline
        would silently fall back to whatever was hard-coded in the
        project.json (or no override at all).
        """
        if not self._project or not self.app_ref:
            return
        frames = getattr(self.app_ref, "_frames", None)
        if not frames:
            return
        voice_frame = frames.get("voices")
        if voice_frame is None:
            return

        try:
            cfg = voice_frame.get_voice_config()
        except Exception:
            return

        provider = (cfg.get("provider") or "").strip()
        voice_id = (cfg.get("voice_id") or "").strip()
        if not provider or not voice_id:
            return

        # Build/merge the project-level VoiceConfig.
        existing = self._project.config.voice or VoiceConfig()
        existing.provider = provider
        existing.voice_id = voice_id
        existing.speed = cfg.get("speed", existing.speed)
        existing.pitch = cfg.get("pitch", existing.pitch)
        existing.stability = cfg.get("stability", existing.stability)
        existing.volume = cfg.get("volume", existing.volume)
        self._project.config.voice = existing

    # ------------------------------------------------------------------
    # File logs
    # ------------------------------------------------------------------
    def _project_log_dir(self) -> Path | None:
        if self._project:
            d = self._project.project_output_dir / "logs"
            d.mkdir(parents=True, exist_ok=True)
            return d
        return None

    def _write_error_log(self, message: str, traceback: str = "") -> None:
        log_dir = self._project_log_dir()
        if not log_dir:
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        project_name = self._project.title if self._project else "unknown"
        line = f"[{ts}] [{project_name}] {message}\n"
        if traceback:
            line += traceback.rstrip("\n") + "\n"
        line += "\n"
        try:
            with open(log_dir / "error_log.txt", "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _write_render_log(self, status: str, detail: str = "") -> None:
        log_dir = self._project_log_dir()
        if not log_dir:
            return
        now = datetime.datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        elapsed = ""
        if hasattr(self, "_render_start_time") and self._render_start_time:
            secs = int((now - self._render_start_time).total_seconds())
            elapsed = f"  elapsed={secs}s"
        project_name = self._project.title if self._project else "unknown"
        scenes = self._project.scene_count if self._project else "?"
        output = self._output_var.get() if hasattr(self, "_output_var") else ""
        line = (
            f"[{ts}] status={status}  project={project_name!r}"
            f"  scenes={scenes}  output={output!r}{elapsed}"
        )
        if detail:
            line += f"\n         detail: {detail}"
        line += "\n"
        try:
            with open(log_dir / "render_log.txt", "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _cancel_render(self):
        if self._pipeline:
            self._pipeline.cancel()
        self._rendering = False
        self._render_btn.configure(text="🚀  Start Render", fg_color=COLORS["accent_primary"])
        self._progress_bar.mark_error("Cancelled")
        self._status.configure(text="Render cancelled", text_color=COLORS["warning"])
        self._resume_btn.grid()  # show resume after cancel

    def _on_render_complete(self, output_path):
        self._rendering = False
        self._render_btn.configure(text="🚀  Start Render", fg_color=COLORS["accent_primary"])
        self._resume_btn.grid_remove()
        self._progress_bar.mark_complete()
        self._status.configure(
            text=f"Render complete! Output: {output_path}",
            text_color=COLORS["success"],
        )
        self._write_render_log("SUCCESS", str(output_path))

    def _on_render_error(self, error, traceback: str = ""):
        self._rendering = False
        self._render_btn.configure(text="🚀  Start Render", fg_color=COLORS["accent_primary"])
        self._progress_bar.mark_error(str(error)[:60])
        self._status.configure(text="Error — see log below", text_color=COLORS["error"])
        self.log_error(str(error))
        self._write_error_log(str(error), traceback)
        self._write_render_log("ERROR", str(error))
        self._resume_btn.grid()  # show resume after error
