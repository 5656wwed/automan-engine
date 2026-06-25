"""Drag-and-drop zone component."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

from app.gui.theme import COLORS, FONTS, SPACING


class DropZone(ctk.CTkFrame):
    """A dashed-border area that accepts drag-and-drop files/folders."""

    def __init__(
        self,
        master,
        on_drop: Optional[Callable[[list[str]], None]] = None,
        accepted_extensions: Optional[set[str]] = None,
        label_text: str = "Drop files here\nor click to browse",
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            **kwargs,
        )
        self._on_drop = on_drop
        self._accepted = accepted_extensions
        self._is_hovering = False

        # Layout
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Inner content
        self._inner = ctk.CTkFrame(self, fg_color="transparent")
        self._inner.grid(row=0, column=0, padx=SPACING["lg"], pady=SPACING["lg"])

        self._icon_label = ctk.CTkLabel(
            self._inner,
            text="📂",
            font=("Segoe UI", 48),
            text_color=COLORS["text_muted"],
        )
        self._icon_label.pack(pady=(0, SPACING["sm"]))

        self._text_label = ctk.CTkLabel(
            self._inner,
            text=label_text,
            font=FONTS["body"],
            text_color=COLORS["text_secondary"],
            justify="center",
        )
        self._text_label.pack()

        self._hint_label = ctk.CTkLabel(
            self._inner,
            text="JSON, PNG, JPG, WEBP, MP4",
            font=FONTS["body_sm"],
            text_color=COLORS["text_muted"],
        )
        self._hint_label.pack(pady=(SPACING["xs"], 0))

        # Click to browse
        self.bind("<Button-1>", self._on_click)
        self._inner.bind("<Button-1>", self._on_click)
        self._icon_label.bind("<Button-1>", self._on_click)
        self._text_label.bind("<Button-1>", self._on_click)

        # Try to register drag-and-drop
        self._setup_dnd()

    def _setup_dnd(self):
        """Try to set up tkinterdnd2 drag-and-drop."""
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<DropEnter>>", self._on_drag_enter)
            self.dnd_bind("<<DropLeave>>", self._on_drag_leave)
            self.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except Exception:
            # tkinterdnd2 not available — click-browse still works
            pass

    def _on_drag_enter(self, event=None):
        self._is_hovering = True
        self.configure(fg_color=COLORS["bg_card_hover"], border_color=COLORS["accent_primary"], border_width=2)
        self._icon_label.configure(text_color=COLORS["accent_primary"])
        self._text_label.configure(text_color=COLORS["accent_light"])

    def _on_drag_leave(self, event=None):
        self._is_hovering = False
        self.configure(fg_color=COLORS["bg_card"], border_width=0)
        self._icon_label.configure(text_color=COLORS["text_muted"])
        self._text_label.configure(text_color=COLORS["text_secondary"])

    def _on_dnd_drop(self, event):
        self._on_drag_leave()
        if event.data:
            # Parse dropped paths (may be space-separated, curly-brace-wrapped)
            raw = event.data
            paths = []
            if "{" in raw:
                # Multiple files: {path1} {path2}
                import re
                paths = re.findall(r"\{(.+?)\}", raw)
            else:
                paths = [raw.strip()]

            filtered = self._filter_paths(paths)
            if filtered and self._on_drop:
                self._on_drop(filtered)

    def _on_click(self, event=None):
        from tkinter import filedialog
        filetypes = [("Project files", "*.json"), ("All files", "*.*")]
        paths = filedialog.askopenfilenames(filetypes=filetypes)
        if paths:
            filtered = self._filter_paths(list(paths))
            if filtered and self._on_drop:
                self._on_drop(filtered)

    def _filter_paths(self, paths: list[str]) -> list[str]:
        """Filter paths by accepted extensions if set."""
        if not self._accepted:
            return paths
        return [p for p in paths if Path(p).suffix.lower() in self._accepted]

    def set_state(self, text: str, icon: str = "✓", color: str = "success"):
        """Update the drop zone to show a loaded state."""
        self._icon_label.configure(text=icon, text_color=COLORS.get(color, COLORS["success"]))
        self._text_label.configure(text=text, text_color=COLORS["text_primary"])
        self._hint_label.configure(text="Click to change")
