"""Enhanced progress bar component — segmented, color-coded."""

from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from app.gui.theme import COLORS, FONTS, SPACING


class RenderProgressBar(ctk.CTkFrame):
    """Multi-segment progress bar showing per-scene render status."""

    def __init__(self, master, total_scenes: int = 1, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._total = total_scenes
        self._segments: list[ctk.CTkFrame] = []
        self._statuses: list[str] = []

        # Overall progress bar
        self._progress_frame = ctk.CTkFrame(self, fg_color=COLORS["progress_bg"], height=8, corner_radius=4)
        self._progress_frame.pack(fill="x", pady=(0, SPACING["sm"]))

        self._progress_fill = ctk.CTkFrame(
            self._progress_frame,
            fg_color=COLORS["accent_primary"],
            height=8,
            corner_radius=4,
            width=0,
        )
        self._progress_fill.place(x=0, y=0, relheight=1.0)

        # Info row
        self._info_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._info_frame.pack(fill="x")

        self._stage_label = ctk.CTkLabel(
            self._info_frame,
            text="Ready",
            font=FONTS["body_sm"],
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._stage_label.pack(side="left")

        self._pct_label = ctk.CTkLabel(
            self._info_frame,
            text="0%",
            font=FONTS["heading_sm"],
            text_color=COLORS["accent_primary"],
            anchor="e",
        )
        self._pct_label.pack(side="right")

        # Scene segments row
        self._segments_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._segments_frame.pack(fill="x", pady=(SPACING["sm"], 0))

        self._build_segments()

    def _build_segments(self):
        for w in self._segments_frame.winfo_children():
            w.destroy()
        self._segments.clear()
        self._statuses.clear()

        for i in range(self._total):
            seg = ctk.CTkFrame(
                self._segments_frame,
                fg_color=COLORS["progress_bg"],
                height=4,
                corner_radius=2,
            )
            seg.pack(side="left", expand=True, fill="x", padx=1)
            self._segments.append(seg)
            self._statuses.append("pending")

    def set_total(self, total: int):
        self._total = total
        self._build_segments()

    def update_progress(self, stage: str, current: int, total: int, pct: float):
        """Update the overall progress display."""
        self._stage_label.configure(text=stage)
        self._pct_label.configure(text=f"{int(pct * 100)}%")

        # Animate fill width
        parent_width = self._progress_frame.winfo_width()
        if parent_width > 1:
            fill_width = int(parent_width * pct)
            self._progress_fill.configure(width=max(fill_width, 0))
            self._progress_fill.place(x=0, y=0, relheight=1.0)

        # Update segments
        for i in range(len(self._segments)):
            if i < current - 1:
                self._set_segment_status(i, "done")
            elif i == current - 1:
                self._set_segment_status(i, "active")

    def _set_segment_status(self, index: int, status: str):
        if 0 <= index < len(self._segments):
            color_map = {
                "pending": COLORS["progress_bg"],
                "active": COLORS["accent_primary"],
                "done": COLORS["success"],
                "error": COLORS["error"],
            }
            self._segments[index].configure(fg_color=color_map.get(status, COLORS["progress_bg"]))
            self._statuses[index] = status

    def mark_complete(self):
        self._stage_label.configure(text="✓ Render complete!", text_color=COLORS["success"])
        self._pct_label.configure(text="100%", text_color=COLORS["success"])
        self._progress_fill.configure(fg_color=COLORS["success"])
        for i in range(len(self._segments)):
            self._set_segment_status(i, "done")

    def mark_error(self, message: str = "Error"):
        self._stage_label.configure(text=f"✗ {message}", text_color=COLORS["error"])
        self._pct_label.configure(text_color=COLORS["error"])

    def reset(self):
        self._stage_label.configure(text="Ready", text_color=COLORS["text_secondary"])
        self._pct_label.configure(text="0%", text_color=COLORS["accent_primary"])
        self._progress_fill.configure(width=0, fg_color=COLORS["accent_primary"])
        for i in range(len(self._segments)):
            self._set_segment_status(i, "pending")
