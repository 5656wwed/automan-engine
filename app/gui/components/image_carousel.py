"""Image carousel component — horizontal scrollable scene previews."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from app.core.project import is_clip_path
from app.gui.theme import COLORS, FONTS, SPACING


def _thumbnail_for(path: Path, size: tuple[int, int]) -> "ctk.CTkImage | None":
    """Return a CTkImage thumbnail for an image or video clip."""
    try:
        if is_clip_path(path):
            return _mp4_thumbnail(path, size)
        img = Image.open(path)
        img.thumbnail(size, Image.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None


def _mp4_thumbnail(path: Path, size: tuple[int, int]) -> "ctk.CTkImage | None":
    """Extract the first frame of an MP4 and return it as a CTkImage."""
    try:
        from app.ffmpeg.detector import get_ffmpeg_path
        ffmpeg = get_ffmpeg_path()
    except Exception:
        return None

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(tmp_fd)
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(path), "-vframes", "1", "-q:v", "2", tmp_path],
            capture_output=True,
            timeout=15,
        )
        img = Image.open(tmp_path)
        img.thumbnail(size, Image.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


class ImageCarousel(ctk.CTkScrollableFrame):
    """Horizontal scrollable row of scene image thumbnails."""

    def __init__(
        self,
        master,
        on_select: Optional[Callable[[int], None]] = None,
        thumb_size: tuple[int, int] = (160, 90),
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=COLORS["bg_dark"],
            orientation="horizontal",
            height=thumb_size[1] + 50,
            **kwargs,
        )
        self._on_select = on_select
        self._thumb_size = thumb_size
        self._thumbnails: list[ctk.CTkButton] = []
        self._images: list[ImageTk.PhotoImage] = []  # prevent GC
        self._selected_index: int = -1

    def load_images(self, image_paths: list[str | Path]) -> None:
        """Load and display scene thumbnails (images or MP4 first-frames)."""
        self.clear()

        for i, path in enumerate(image_paths):
            path = Path(path)
            is_video = is_clip_path(path)
            photo = _thumbnail_for(path, self._thumb_size)

            frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=8)
            frame.pack(side="left", padx=SPACING["xs"], pady=SPACING["xs"])

            if photo:
                btn = ctk.CTkButton(
                    frame,
                    image=photo,
                    text="🎬" if is_video else "",
                    fg_color=COLORS["bg_card"],
                    hover_color=COLORS["bg_card_hover"],
                    corner_radius=6,
                    width=self._thumb_size[0],
                    height=self._thumb_size[1],
                    command=lambda idx=i: self._select(idx),
                )
            else:
                btn = ctk.CTkButton(
                    frame,
                    text="🎬" if is_video else "⚠",
                    fg_color=COLORS["bg_card"],
                    hover_color=COLORS["bg_card_hover"],
                    corner_radius=6,
                    width=self._thumb_size[0],
                    height=self._thumb_size[1],
                    command=lambda idx=i: self._select(idx),
                )

            btn.pack(padx=2, pady=2)

            label = ctk.CTkLabel(
                frame,
                text=f"Scene {i + 1}",
                font=FONTS["body_sm"],
                text_color=COLORS["text_secondary"],
            )
            label.pack(pady=(0, SPACING["xs"]))

            self._thumbnails.append(btn)
            if photo:
                self._images.append(photo)

    def _select(self, index: int) -> None:
        """Handle thumbnail selection."""
        # Deselect previous
        if 0 <= self._selected_index < len(self._thumbnails):
            self._thumbnails[self._selected_index].configure(
                fg_color=COLORS["bg_card"],
                border_width=0,
            )

        # Select new
        self._selected_index = index
        if 0 <= index < len(self._thumbnails):
            self._thumbnails[index].configure(
                fg_color=COLORS["bg_card_hover"],
                border_color=COLORS["accent_primary"],
                border_width=2,
            )

        if self._on_select:
            self._on_select(index)

    def clear(self) -> None:
        """Remove all thumbnails."""
        for widget in self.winfo_children():
            widget.destroy()
        self._thumbnails.clear()
        self._images.clear()
        self._selected_index = -1
