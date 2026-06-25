"""Project frame — load project JSON, preview images and scenes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from app.core.project import Project, load_project
from app.gui.components.drop_zone import DropZone
from app.gui.components.image_carousel import ImageCarousel
from app.gui.theme import COLORS, FONTS, SPACING


class ProjectFrame(ctk.CTkFrame):
    """Project loading and scene preview panel."""

    def __init__(self, master, app_ref=None, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], corner_radius=0, **kwargs)
        self.app_ref = app_ref
        self.project: Optional[Project] = None

        self._build_ui()

    def _build_ui(self):
        # Header
        header = ctk.CTkLabel(
            self, text="📁 Project", font=FONTS["heading_lg"],
            text_color=COLORS["text_primary"], anchor="w",
        )
        header.pack(fill="x", padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        subtitle = ctk.CTkLabel(
            self, text="Load a project JSON file or drag & drop a project folder",
            font=FONTS["body"], text_color=COLORS["text_secondary"], anchor="w",
        )
        subtitle.pack(fill="x", padx=SPACING["lg"], pady=(0, SPACING["md"]))

        # Drop zone
        self._drop_zone = DropZone(
            self,
            on_drop=self._on_files_dropped,
            accepted_extensions={".json"},
            label_text="Drop project.json here\nor click to browse",
        )
        self._drop_zone.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"], ipady=SPACING["xl"])

        # Project info card (hidden initially)
        self._info_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)

        self._title_label = ctk.CTkLabel(
            self._info_card, text="", font=FONTS["heading_md"],
            text_color=COLORS["text_primary"], anchor="w",
        )
        self._title_label.pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        self._meta_label = ctk.CTkLabel(
            self._info_card, text="", font=FONTS["body"],
            text_color=COLORS["text_secondary"], anchor="w",
        )
        self._meta_label.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))

        # Image carousel
        self._carousel_label = ctk.CTkLabel(
            self, text="Scene Previews", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        )

        self._carousel = ImageCarousel(self, on_select=self._on_scene_select)

        # Scene detail card
        self._scene_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)

        self._scene_title = ctk.CTkLabel(
            self._scene_card, text="", font=FONTS["heading_sm"],
            text_color=COLORS["accent_primary"], anchor="w",
        )
        self._scene_title.pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        self._scene_script = ctk.CTkTextbox(
            self._scene_card, font=FONTS["body"], height=100,
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8,
        )
        self._scene_script.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))

        # Validation status
        self._status_label = ctk.CTkLabel(
            self, text="", font=FONTS["body_sm"],
            text_color=COLORS["text_muted"], anchor="w",
        )

    def _on_files_dropped(self, paths: list[str]):
        if paths:
            self._load_project(paths[0])

    def _load_project(self, json_path: str):
        try:
            self.project = load_project(json_path)

            # Update drop zone
            self._drop_zone.set_state(
                text=f"Loaded: {Path(json_path).name}",
                icon="✓",
                color="success",
            )

            # Show info card
            self._info_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])
            self._title_label.configure(text=self.project.title)
            self._meta_label.configure(
                text=f"{self.project.scene_count} scenes  •  "
                     f"{self.project.config.resolution}  •  "
                     f"{self.project.config.fps} FPS",
            )

            # Load carousel
            image_paths = [s.image for s in self.project.scenes]
            self._carousel_label.pack(fill="x", padx=SPACING["lg"], pady=(SPACING["md"], SPACING["xs"]))
            self._carousel.pack(fill="x", padx=SPACING["lg"], pady=SPACING["xs"])
            self._carousel.load_images(image_paths)

            # Validation
            errors = self.project.validate()
            if errors:
                self._status_label.configure(
                    text=f"⚠ {len(errors)} warning(s): {errors[0]}",
                    text_color=COLORS["warning"],
                )
            else:
                self._status_label.configure(
                    text="✓ Project is valid and ready to render",
                    text_color=COLORS["success"],
                )
            self._status_label.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

            # Notify app
            if self.app_ref:
                self.app_ref.on_project_loaded(self.project)

        except Exception as e:
            self._drop_zone.set_state(text=f"Error: {e}", icon="✗", color="error")

    def _on_scene_select(self, index: int):
        if self.project and 0 <= index < self.project.scene_count:
            scene = self.project.scenes[index]
            self._scene_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])
            self._scene_title.configure(text=f"Scene {index + 1} — {Path(scene.image).name}")
            self._scene_script.delete("1.0", "end")
            self._scene_script.insert("1.0", scene.script)
