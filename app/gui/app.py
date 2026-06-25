"""AutoScene Studio — Main GUI application window."""

from __future__ import annotations

import customtkinter as ctk

from app import __app_name__, __version__
from app.core.project import Project
from app.gui.theme import COLORS, DIMENSIONS, FONTS, NAV_ITEMS, SPACING
from app.gui.frames.project_frame import ProjectFrame
from app.gui.frames.voice_frame import VoiceFrame
from app.gui.frames.render_frame import RenderFrame
from app.gui.frames.settings_frame import SettingsFrame
from app.gui.frames.logs_frame import LogsFrame


ctk.set_appearance_mode("dark")


class AutoSceneApp(ctk.CTk):
    """Main application window with sidebar navigation."""

    def __init__(self):
        super().__init__()

        self.title(f"{__app_name__} v{__version__}")
        self.geometry(f"{DIMENSIONS['window_width']}x{DIMENSIONS['window_height']}")
        self.minsize(DIMENSIONS["min_width"], DIMENSIONS["min_height"])
        self.configure(fg_color=COLORS["bg_darkest"])

        # State
        self._current_frame_id = "project"
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._frames: dict[str, ctk.CTkFrame] = {}

        self._build_layout()
        self._show_frame("project")

    def _build_layout(self):
        # Root grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ──────────────────────────────────────────────
        sidebar = ctk.CTkFrame(
            self, fg_color=COLORS["bg_medium"],
            width=DIMENSIONS["sidebar_width"], corner_radius=0,
        )
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        # Logo area
        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=SPACING["md"], pady=(SPACING["lg"], SPACING["md"]))

        ctk.CTkLabel(
            logo_frame, text="🎬", font=("Segoe UI", 32),
        ).pack(anchor="w")
        ctk.CTkLabel(
            logo_frame, text="AutoScene", font=FONTS["heading_md"],
            text_color=COLORS["accent_primary"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            logo_frame, text="Studio", font=FONTS["heading_sm"],
            text_color=COLORS["text_muted"],
        ).pack(anchor="w")

        # Separator
        ctk.CTkFrame(sidebar, fg_color=COLORS["border"], height=1).pack(
            fill="x", padx=SPACING["md"], pady=SPACING["sm"],
        )

        # Nav buttons
        for item in NAV_ITEMS:
            btn = ctk.CTkButton(
                sidebar,
                text=item["label"],
                font=FONTS["nav"],
                fg_color="transparent",
                hover_color=COLORS["bg_card_hover"],
                text_color=COLORS["text_secondary"],
                anchor="w",
                height=42,
                corner_radius=8,
                command=lambda fid=item["id"]: self._show_frame(fid),
            )
            btn.pack(fill="x", padx=SPACING["sm"], pady=2)
            self._nav_buttons[item["id"]] = btn

        # Bottom spacer + version + New Window
        sidebar_bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        sidebar_bottom.pack(side="bottom", fill="x", padx=SPACING["md"], pady=SPACING["md"])

        def _open_new_window():
            import subprocess
            import sys
            subprocess.Popen([sys.executable] + sys.argv)

        ctk.CTkButton(
            sidebar_bottom,
            text="+ New Window",
            font=FONTS["body_sm"],
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_primary"],
            height=30,
            command=_open_new_window
        ).pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            sidebar_bottom, text=f"v{__version__}",
            font=FONTS["body_sm"], text_color=COLORS["text_muted"],
        ).pack(anchor="w")

        # ── Content area ──────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Create all frames
        self._frames["project"] = ProjectFrame(content, app_ref=self)
        self._frames["voices"] = VoiceFrame(content, app_ref=self)
        self._frames["render"] = RenderFrame(content, app_ref=self)
        self._frames["settings"] = SettingsFrame(content, app_ref=self)
        self._frames["logs"] = LogsFrame(content, app_ref=self)

        for frame in self._frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

    def _show_frame(self, frame_id: str):
        """Switch to a specific frame and update nav highlighting."""
        # Update nav
        for fid, btn in self._nav_buttons.items():
            if fid == frame_id:
                btn.configure(
                    fg_color=COLORS["bg_card"],
                    text_color=COLORS["accent_primary"],
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_secondary"],
                )

        # Show frame
        self._frames[frame_id].tkraise()
        self._current_frame_id = frame_id

        # Lazy init voices
        if frame_id == "voices":
            self._frames["voices"].initialize()

    def on_project_loaded(self, project: Project):
        """Called by ProjectFrame when a project is loaded."""
        self._frames["render"].set_project(project)


if __name__ == "__main__":
    app = AutoSceneApp()
    app.mainloop()
