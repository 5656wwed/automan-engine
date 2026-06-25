"""Settings frame — API keys, FFmpeg path, defaults, cache management."""

from __future__ import annotations

import customtkinter as ctk

from app.core.config import get_config, reload_config, save_config
from app.gui.theme import COLORS, FONTS, SPACING
from app.utils.cache import CacheManager


# Map of attr-key -> (display label, config field on AppConfig)
API_KEY_FIELDS = [
    ("elevenlabs_key", "ElevenLabs API Key", "elevenlabs_api_key"),
    ("openai_key",     "OpenAI API Key",     "openai_api_key"),
    ("ai33pro_key",    "AI33Pro API Key",    "ai33pro_api_key"),
    ("fishaudio_key",  "Fish Audio API Key",  "fish_audio_api_key"),
    ("inworld_key",    "Inworld API Key",     "inworld_api_key"),
    ("groq_key",       "Groq API Key",        "groq_api_key"),
]


class SettingsFrame(ctk.CTkFrame):
    """Application settings and API configuration panel."""

    def __init__(self, master, app_ref=None, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], corner_radius=0, **kwargs)
        self.app_ref = app_ref
        # Track each per-key save button so we can flash status on it
        self._row_save_buttons: dict[str, ctk.CTkButton] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_dark"])
        scroll.pack(fill="both", expand=True)

        # Header
        ctk.CTkLabel(
            scroll, text="⚙ Settings", font=FONTS["heading_lg"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["md"]))

        # --- API Keys section ---
        api_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        api_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            api_card, text="🔑 API Keys", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        ctk.CTkLabel(
            api_card,
            text=(
                "Enter the key for each TTS provider you want to use, then click "
                "Save next to it. Keys are stored privately in your user profile "
                "(never committed to the project folder)."
            ),
            font=FONTS["body_sm"], text_color=COLORS["text_muted"],
            anchor="w", justify="left", wraplength=720,
        ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))

        # One row per API key, with its own Save button
        for attr, label, _config_field in API_KEY_FIELDS:
            self._build_api_key_row(api_card, label, attr)

        # Bottom action row: Clear all + Save all
        btn_row = ctk.CTkFrame(api_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=SPACING["md"], pady=(SPACING["sm"], SPACING["md"]))

        self._clear_btn = ctk.CTkButton(
            btn_row, text="🗑 Clear All Keys", font=FONTS["button"],
            fg_color="transparent", border_width=1, border_color=COLORS["error"],
            text_color=COLORS["error"], hover_color="#2d1a1a", corner_radius=8,
            height=36, width=140,
            command=self._clear_api_keys,
        )
        self._clear_btn.pack(side="left")

        self._save_all_btn = ctk.CTkButton(
            btn_row, text="💾 Save All", font=FONTS["button"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
            text_color="white", corner_radius=8, height=36, width=120,
            command=self._save_all_api_keys,
        )
        self._save_all_btn.pack(side="right")

        # --- Inworld Custom Voices section ---
        self._build_inworld_custom_voices_card(scroll)

        # --- FFmpeg section ---
        ffmpeg_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        ffmpeg_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            ffmpeg_card, text="🎥 FFmpeg", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        self._ffmpeg_status = ctk.CTkLabel(
            ffmpeg_card, text="Checking...", font=FONTS["body"],
            text_color=COLORS["text_secondary"], anchor="w",
        )
        self._ffmpeg_status.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"]))

        path_row = ctk.CTkFrame(ffmpeg_card, fg_color="transparent")
        path_row.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))

        self._ffmpeg_path_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            path_row, textvariable=self._ffmpeg_path_var,
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8,
            height=36, placeholder_text="Auto-detect (leave blank)",
        ).pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

        ctk.CTkButton(
            path_row, text="Test", font=FONTS["body_sm"],
            fg_color=COLORS["accent_dark"], hover_color=COLORS["accent_primary"],
            text_color="white", corner_radius=6, height=36, width=70,
            command=self._test_ffmpeg,
        ).pack(side="right")

        # --- Defaults section ---
        defaults_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        defaults_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            defaults_card, text="🎯 Defaults", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["sm"]))

        grid = ctk.CTkFrame(defaults_card, fg_color="transparent")
        grid.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))
        grid.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(grid, text="Default Motion", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w")
        self._motion_var = ctk.StringVar(value="zoom_out")
        ctk.CTkOptionMenu(
            grid, variable=self._motion_var,
            values=["zoom_in", "zoom_out", "pan_left", "pan_right", "camera_drift", "none"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            text_color=COLORS["text_primary"], width=160,
        ).grid(row=1, column=0, sticky="w", pady=SPACING["xs"])

        ctk.CTkLabel(grid, text="Randomize motion per scene", font=FONTS["label"], text_color=COLORS["text_secondary"]).grid(row=0, column=1, sticky="w", padx=SPACING["md"])
        self._randomize_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            grid, text="Enable auto-motion",
            variable=self._randomize_var,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_dark"],
            text_color=COLORS["text_secondary"],
            font=FONTS["body_sm"],
        ).grid(row=1, column=1, sticky="w", padx=SPACING["md"], pady=SPACING["xs"])

        # --- Overlay Text section ---
        self._build_overlay_card(scroll)

        # --- MP4 Video Scenes section ---
        self._build_mp4_card(scroll)

        # --- Background Music section ---
        self._build_bg_music_card(scroll)

        # --- Cache section ---
        cache_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        cache_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            cache_card, text="💾 Cache", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        self._cache_status = ctk.CTkLabel(
            cache_card, text="", font=FONTS["body"],
            text_color=COLORS["text_secondary"], anchor="w",
        )
        self._cache_status.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"]))

        ctk.CTkButton(
            cache_card, text="🗑 Clear Cache", font=FONTS["button"],
            fg_color=COLORS["error"], hover_color="#dc2626",
            text_color="white", corner_radius=8, height=36, width=140,
            command=self._clear_cache,
        ).pack(padx=SPACING["md"], pady=(0, SPACING["md"]), anchor="w")

        # Load initial state
        self.after(100, self._load_state)

    def _build_overlay_card(self, parent) -> None:
        """Overlay Text settings: font size, SFX volume, typing duration."""
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            card, text="Overlay Text", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        ctk.CTkLabel(
            card,
            text="Controls for the typewriter text animation (dates, locations, numbers) shown during render.",
            font=FONTS["body_sm"], text_color=COLORS["text_muted"],
            anchor="w", wraplength=720,
        ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))

        # Font file selection row
        font_file_row = ctk.CTkFrame(card, fg_color="transparent")
        font_file_row.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))

        ctk.CTkLabel(
            font_file_row, text="Custom Font File (.ttf)", font=FONTS["label"],
            text_color=COLORS["text_secondary"], width=160, anchor="w",
        ).pack(side="left")

        self._overlay_font_path_var = ctk.StringVar(value="")
        self._overlay_font_entry = ctk.CTkEntry(
            font_file_row, textvariable=self._overlay_font_path_var,
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8,
            height=36, placeholder_text="Default (Tox Typewriter.ttf / System default)",
        )
        self._overlay_font_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

        ctk.CTkButton(
            font_file_row, text="📁 Browse", font=FONTS["body_sm"],
            fg_color=COLORS["accent_dark"], hover_color=COLORS["accent_primary"],
            text_color="white", corner_radius=6, height=36, width=80,
            command=self._browse_font_file,
        ).pack(side="right")

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))
        grid.grid_columnconfigure((0, 1, 2), weight=1)

        # ── Font Size ──────────────────────────────────────────────────
        ctk.CTkLabel(
            grid, text="Font Size", font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", padx=SPACING["xs"])

        self._overlay_font_size_var = ctk.IntVar(value=130)
        font_row = ctk.CTkFrame(grid, fg_color="transparent")
        font_row.grid(row=1, column=0, sticky="ew", padx=SPACING["xs"], pady=SPACING["xs"])

        self._overlay_font_size_label = ctk.CTkLabel(
            font_row, text="130", font=FONTS["body_sm"],
            text_color=COLORS["accent_primary"], width=36,
        )
        self._overlay_font_size_label.pack(side="right")

        ctk.CTkSlider(
            font_row, from_=60, to=200, number_of_steps=28,
            variable=self._overlay_font_size_var,
            fg_color=COLORS["bg_input"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_primary"], button_hover_color=COLORS["accent_dark"],
            command=lambda v: self._overlay_font_size_label.configure(text=str(int(v))),
        ).pack(side="left", fill="x", expand=True)

        # ── SFX Volume ────────────────────────────────────────────────
        ctk.CTkLabel(
            grid, text="SFX Volume", font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=1, sticky="w", padx=SPACING["xs"])

        self._overlay_sfx_vol_var = ctk.DoubleVar(value=0.55)
        sfx_row = ctk.CTkFrame(grid, fg_color="transparent")
        sfx_row.grid(row=1, column=1, sticky="ew", padx=SPACING["xs"], pady=SPACING["xs"])

        self._overlay_sfx_vol_label = ctk.CTkLabel(
            sfx_row, text="55%", font=FONTS["body_sm"],
            text_color=COLORS["accent_primary"], width=36,
        )
        self._overlay_sfx_vol_label.pack(side="right")

        ctk.CTkSlider(
            sfx_row, from_=0.0, to=1.0, number_of_steps=20,
            variable=self._overlay_sfx_vol_var,
            fg_color=COLORS["bg_input"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_primary"], button_hover_color=COLORS["accent_dark"],
            command=lambda v: self._overlay_sfx_vol_label.configure(text=f"{int(v*100)}%"),
        ).pack(side="left", fill="x", expand=True)

        # ── Typing Duration ───────────────────────────────────────────
        ctk.CTkLabel(
            grid, text="Typing Duration (s)", font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=2, sticky="w", padx=SPACING["xs"])

        self._overlay_type_dur_var = ctk.DoubleVar(value=2.0)
        dur_row = ctk.CTkFrame(grid, fg_color="transparent")
        dur_row.grid(row=1, column=2, sticky="ew", padx=SPACING["xs"], pady=SPACING["xs"])

        self._overlay_type_dur_label = ctk.CTkLabel(
            dur_row, text="2.0s", font=FONTS["body_sm"],
            text_color=COLORS["accent_primary"], width=36,
        )
        self._overlay_type_dur_label.pack(side="right")

        ctk.CTkSlider(
            dur_row, from_=0.5, to=5.0, number_of_steps=18,
            variable=self._overlay_type_dur_var,
            fg_color=COLORS["bg_input"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_primary"], button_hover_color=COLORS["accent_dark"],
            command=lambda v: self._overlay_type_dur_label.configure(text=f"{v:.1f}s"),
        ).pack(side="left", fill="x", expand=True)

        # ── Save button ───────────────────────────────────────────────
        self._overlay_save_btn = ctk.CTkButton(
            card, text="Save Overlay Settings", font=FONTS["button"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
            text_color="white", corner_radius=8, height=36, width=180,
            command=self._save_overlay_settings,
        )
        self._overlay_save_btn.pack(anchor="e", padx=SPACING["md"], pady=(0, SPACING["md"]))

    def _build_mp4_card(self, parent) -> None:
        """MP4 Video Scenes: background audio volume."""
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            card, text="🎬 MP4 Video Scenes", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        ctk.CTkLabel(
            card,
            text=(
                "When a scene uses an MP4 file, its original audio is mixed under the voiceover "
                "at this volume. 0% = silent. If the MP4 is shorter than the TTS audio it is "
                "automatically slowed down to fill the scene; if longer it is trimmed."
            ),
            font=FONTS["body_sm"], text_color=COLORS["text_muted"],
            anchor="w", wraplength=720, justify="left",
        ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))

        vol_grid = ctk.CTkFrame(card, fg_color="transparent")
        vol_grid.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))
        vol_grid.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            vol_grid, text="MP4 Audio Volume", font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", padx=SPACING["xs"])

        self._mp4_vol_var = ctk.DoubleVar(value=0.08)
        mp4_vol_row = ctk.CTkFrame(vol_grid, fg_color="transparent")
        mp4_vol_row.grid(row=1, column=0, sticky="ew", padx=SPACING["xs"], pady=SPACING["xs"])

        self._mp4_vol_label = ctk.CTkLabel(
            mp4_vol_row, text="8%", font=FONTS["body_sm"],
            text_color=COLORS["accent_primary"], width=36,
        )
        self._mp4_vol_label.pack(side="right")

        ctk.CTkSlider(
            mp4_vol_row, from_=0.0, to=0.30, number_of_steps=30,
            variable=self._mp4_vol_var,
            fg_color=COLORS["bg_input"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_primary"], button_hover_color=COLORS["accent_dark"],
            command=lambda v: self._mp4_vol_label.configure(text=f"{int(v * 100)}%"),
        ).pack(side="left", fill="x", expand=True)

        self._mp4_save_btn = ctk.CTkButton(
            card, text="Save MP4 Settings", font=FONTS["button"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
            text_color="white", corner_radius=8, height=36, width=180,
            command=self._save_mp4_settings,
        )
        self._mp4_save_btn.pack(anchor="e", padx=SPACING["md"], pady=(0, SPACING["md"]))

    def _build_bg_music_card(self, parent) -> None:
        """Background Music: enable toggle + volume slider."""
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            card, text="Background Music", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        ctk.CTkLabel(
            card,
            text="Randomly picks a track from the bg_music/ folder and mixes it under the voiceover.",
            font=FONTS["body_sm"], text_color=COLORS["text_muted"],
            anchor="w", wraplength=720,
        ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))

        # Enable toggle row
        toggle_row = ctk.CTkFrame(card, fg_color="transparent")
        toggle_row.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"]))

        self._bg_music_enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toggle_row, text="Enable background music",
            variable=self._bg_music_enabled_var,
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_dark"],
            text_color=COLORS["text_secondary"],
            font=FONTS["body_sm"],
        ).pack(side="left")

        # Volume slider row
        vol_grid = ctk.CTkFrame(card, fg_color="transparent")
        vol_grid.pack(fill="x", padx=SPACING["md"], pady=(SPACING["xs"], SPACING["sm"]))
        vol_grid.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            vol_grid, text="Music Volume", font=FONTS["label"],
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", padx=SPACING["xs"])

        self._bg_music_vol_var = ctk.DoubleVar(value=0.20)
        vol_row = ctk.CTkFrame(vol_grid, fg_color="transparent")
        vol_row.grid(row=1, column=0, sticky="ew", padx=SPACING["xs"], pady=SPACING["xs"])

        self._bg_music_vol_label = ctk.CTkLabel(
            vol_row, text="20%", font=FONTS["body_sm"],
            text_color=COLORS["accent_primary"], width=36,
        )
        self._bg_music_vol_label.pack(side="right")

        ctk.CTkSlider(
            vol_row, from_=0.0, to=1.0, number_of_steps=20,
            variable=self._bg_music_vol_var,
            fg_color=COLORS["bg_input"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_primary"], button_hover_color=COLORS["accent_dark"],
            command=lambda v: self._bg_music_vol_label.configure(text=f"{int(v * 100)}%"),
        ).pack(side="left", fill="x", expand=True)

        # Save button
        self._bg_music_save_btn = ctk.CTkButton(
            card, text="Save Music Settings", font=FONTS["button"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
            text_color="white", corner_radius=8, height=36, width=180,
            command=self._save_bg_music_settings,
        )
        self._bg_music_save_btn.pack(anchor="e", padx=SPACING["md"], pady=(0, SPACING["md"]))

    def _build_inworld_custom_voices_card(self, parent) -> None:
        """Build the Inworld custom voices management card."""
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            card, text="🎙 Inworld Custom Voices",
            font=FONTS["heading_sm"], text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        ctk.CTkLabel(
            card,
            text="Add your custom Inworld voice IDs here. They appear at the top of the voice list.",
            font=FONTS["body_sm"], text_color=COLORS["text_muted"],
            anchor="w", justify="left", wraplength=720,
        ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["sm"]))

        # Scrollable list area for existing custom voices
        self._inworld_voice_list_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._inworld_voice_list_frame.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"]))

        # Add form row
        add_row = ctk.CTkFrame(card, fg_color="transparent")
        add_row.pack(fill="x", padx=SPACING["md"], pady=(SPACING["xs"], SPACING["md"]))

        self._inworld_name_entry = ctk.CTkEntry(
            add_row, placeholder_text="Display name",
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8, height=34,
        )
        self._inworld_name_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

        self._inworld_id_entry = ctk.CTkEntry(
            add_row, placeholder_text="Voice ID",
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8, height=34,
        )
        self._inworld_id_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))

        ctk.CTkButton(
            add_row, text="＋ Add", font=FONTS["body_sm"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
            text_color="white", corner_radius=8, height=34, width=80,
            command=self._add_inworld_custom_voice,
        ).pack(side="right")

        self._refresh_inworld_voice_list()

    def _refresh_inworld_voice_list(self) -> None:
        """Clear and rebuild the list of saved custom Inworld voices."""
        for widget in self._inworld_voice_list_frame.winfo_children():
            widget.destroy()

        config = get_config()
        voices = config.inworld_custom_voices or []

        if not voices:
            ctk.CTkLabel(
                self._inworld_voice_list_frame,
                text="No custom voices added yet.",
                font=FONTS["body_sm"], text_color=COLORS["text_muted"], anchor="w",
            ).pack(fill="x")
            return

        for i, voice in enumerate(voices):
            row = ctk.CTkFrame(self._inworld_voice_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row,
                text=f"{voice.get('name', '?')}  —  {voice.get('id', '?')}",
                font=FONTS["body_sm"], text_color=COLORS["text_secondary"], anchor="w",
            ).pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                row, text="✕", font=FONTS["body_sm"],
                fg_color="transparent", text_color=COLORS["error"],
                hover_color="#2d1a1a", corner_radius=6, height=26, width=32,
                command=lambda idx=i: self._delete_inworld_custom_voice(idx),
            ).pack(side="right")

    def _add_inworld_custom_voice(self) -> None:
        """Validate entries, persist new custom voice, refresh list."""
        name = self._inworld_name_entry.get().strip()
        voice_id = self._inworld_id_entry.get().strip()

        if not name or not voice_id:
            return

        config = get_config()
        voices = list(config.inworld_custom_voices or [])
        voices.append({"id": voice_id, "name": name})
        config.inworld_custom_voices = voices
        save_config(config)
        reload_config()

        self._inworld_name_entry.delete(0, "end")
        self._inworld_id_entry.delete(0, "end")
        self._refresh_inworld_voice_list()
        self._refresh_voice_frame()

    def _delete_inworld_custom_voice(self, index: int) -> None:
        """Remove custom voice at given index, persist, refresh list."""
        config = get_config()
        voices = list(config.inworld_custom_voices or [])
        if 0 <= index < len(voices):
            voices.pop(index)
            config.inworld_custom_voices = voices
            save_config(config)
            reload_config()
            self._refresh_inworld_voice_list()
            self._refresh_voice_frame()

    def _build_api_key_row(self, parent, label: str, attr: str) -> None:
        """Build a single API-key row with: label + entry + Save button."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=SPACING["md"], pady=SPACING["xs"])

        ctk.CTkLabel(
            row, text=label, font=FONTS["label"],
            text_color=COLORS["text_secondary"], width=160, anchor="w",
        ).pack(side="left")

        entry = ctk.CTkEntry(
            row, fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            border_color=COLORS["border"], border_width=1, corner_radius=8,
            height=36, show="•", placeholder_text="Not configured",
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["xs"]))
        setattr(self, f"_entry_{attr}", entry)

        save_btn = ctk.CTkButton(
            row, text="💾 Save", font=FONTS["body_sm"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_dark"],
            text_color="white", corner_radius=8, height=36, width=80,
            command=lambda a=attr: self._save_single_api_key(a),
        )
        save_btn.pack(side="right")
        self._row_save_buttons[attr] = save_btn

    # ------------------------------------------------------------------
    # State load / save
    # ------------------------------------------------------------------
    def _load_state(self):
        # FFmpeg check
        self._test_ffmpeg()

        # Load keys from current config — but never pre-populate from an
        # in-program default; we only show what the user previously saved.
        config = get_config()
        for attr, _label, field in API_KEY_FIELDS:
            entry = getattr(self, f"_entry_{attr}", None)
            if entry is None:
                continue
            entry.delete(0, "end")
            value = getattr(config, field, None) or ""
            entry.insert(0, value)

        # Overlay settings
        fs  = int(getattr(config, "overlay_font_size",    130))
        vol = float(getattr(config, "overlay_sfx_volume",  0.55))
        dur = float(getattr(config, "overlay_type_duration", 2.0))
        self._overlay_font_size_var.set(fs)
        self._overlay_sfx_vol_var.set(vol)
        self._overlay_type_dur_var.set(dur)
        self._overlay_font_size_label.configure(text=str(fs))
        self._overlay_sfx_vol_label.configure(text=f"{int(vol*100)}%")
        self._overlay_type_dur_label.configure(text=f"{dur:.1f}s")
        
        font_path = getattr(config, "overlay_font_path", None) or ""
        self._overlay_font_path_var.set(font_path)

        # MP4 video scene settings
        mp4_vol = float(getattr(config, "mp4_bg_volume", 0.08))
        self._mp4_vol_var.set(mp4_vol)
        self._mp4_vol_label.configure(text=f"{int(mp4_vol * 100)}%")

        # Background music settings
        bg_enabled = bool(getattr(config, "bg_music_enabled", False))
        bg_vol = float(getattr(config, "bg_music_volume", 0.20))
        self._bg_music_enabled_var.set(bg_enabled)
        self._bg_music_vol_var.set(bg_vol)
        self._bg_music_vol_label.configure(text=f"{int(bg_vol * 100)}%")

        # Cache stats
        try:
            cm = CacheManager()
            stats = cm.get_cache_stats()
            self._cache_status.configure(
                text=f"{stats['entries']} cached items • {stats['size_mb']} MB",
            )
        except Exception:
            self._cache_status.configure(text="Cache not available")

    def _test_ffmpeg(self):
        try:
            from app.ffmpeg.detector import detect_ffmpeg
            info = detect_ffmpeg()
            self._ffmpeg_status.configure(
                text=f"✓ FFmpeg v{info.version} — {info.path}",
                text_color=COLORS["success"],
            )
        except Exception as e:
            self._ffmpeg_status.configure(
                text=f"✗ FFmpeg not found: {e}",
                text_color=COLORS["error"],
            )

    def _clear_cache(self):
        try:
            cm = CacheManager()
            count = cm.clear_cache()
            self._cache_status.configure(text=f"Cache cleared ({count} files removed)")
        except Exception as e:
            self._cache_status.configure(text=f"Error: {e}", text_color=COLORS["error"])

    # ------------------------------------------------------------------
    # API key save flows
    # ------------------------------------------------------------------
    def _persist_keys_from_ui(self) -> None:
        """Read all key inputs and write them to settings.json."""
        config = get_config()
        for attr, _label, field in API_KEY_FIELDS:
            entry = getattr(self, f"_entry_{attr}", None)
            if entry is None:
                continue
            value = entry.get().strip()
            setattr(config, field, value or None)
        save_config(config)
        # Refresh the global config singleton so other parts of the app
        # see the new values without restarting.
        reload_config()
        # Tell the voice frame to re-fetch voices using the new keys.
        self._refresh_voice_frame()

    def _save_single_api_key(self, attr: str) -> None:
        """Save just one provider's key, then flash that row's button."""
        try:
            self._persist_keys_from_ui()
            btn = self._row_save_buttons.get(attr)
            if btn is not None:
                btn.configure(text="✓ Saved", fg_color=COLORS["success"])
                self.after(2000, lambda b=btn: b.configure(
                    text="💾 Save", fg_color=COLORS["accent_primary"]
                ))
        except Exception as e:
            btn = self._row_save_buttons.get(attr)
            if btn is not None:
                btn.configure(text="✗ Error", fg_color=COLORS["error"])
                self.after(2500, lambda b=btn: b.configure(
                    text="💾 Save", fg_color=COLORS["accent_primary"]
                ))
            print(f"Error saving {attr}: {e}")

    def _save_all_api_keys(self) -> None:
        """Save every key at once."""
        try:
            self._persist_keys_from_ui()
            self._save_all_btn.configure(text="✓ Saved!", fg_color=COLORS["success"])
            self.after(2000, lambda: self._save_all_btn.configure(
                text="💾 Save All", fg_color=COLORS["accent_primary"]
            ))
        except Exception as e:
            self._save_all_btn.configure(text="✗ Error", fg_color=COLORS["error"])
            print(f"Error saving config: {e}")
            self.after(2500, lambda: self._save_all_btn.configure(
                text="💾 Save All", fg_color=COLORS["accent_primary"]
            ))

    def _save_mp4_settings(self) -> None:
        try:
            config = get_config()
            config.mp4_bg_volume = round(float(self._mp4_vol_var.get()), 3)
            save_config(config)
            reload_config()
            self._mp4_save_btn.configure(text="Saved!", fg_color=COLORS["success"])
            self.after(2000, lambda: self._mp4_save_btn.configure(
                text="Save MP4 Settings", fg_color=COLORS["accent_primary"]
            ))
        except Exception as e:
            self._mp4_save_btn.configure(text="Error", fg_color=COLORS["error"])
            self.after(2500, lambda: self._mp4_save_btn.configure(
                text="Save MP4 Settings", fg_color=COLORS["accent_primary"]
            ))
            print(f"Error saving MP4 settings: {e}")

    def _save_bg_music_settings(self) -> None:
        try:
            config = get_config()
            config.bg_music_enabled = bool(self._bg_music_enabled_var.get())
            config.bg_music_volume = round(float(self._bg_music_vol_var.get()), 2)
            save_config(config)
            reload_config()
            self._bg_music_save_btn.configure(text="Saved!", fg_color=COLORS["success"])
            self.after(2000, lambda: self._bg_music_save_btn.configure(
                text="Save Music Settings", fg_color=COLORS["accent_primary"]
            ))
        except Exception as e:
            self._bg_music_save_btn.configure(text="Error", fg_color=COLORS["error"])
            self.after(2500, lambda: self._bg_music_save_btn.configure(
                text="Save Music Settings", fg_color=COLORS["accent_primary"]
            ))
            print(f"Error saving bg music settings: {e}")

    def _save_overlay_settings(self) -> None:
        try:
            config = get_config()
            config.overlay_font_size    = int(self._overlay_font_size_var.get())
            config.overlay_sfx_volume   = round(float(self._overlay_sfx_vol_var.get()), 2)
            config.overlay_type_duration = round(float(self._overlay_type_dur_var.get()), 1)
            
            val = self._overlay_font_path_var.get().strip()
            config.overlay_font_path = val if val else None
            
            save_config(config)
            reload_config()
            self._overlay_save_btn.configure(text="Saved!", fg_color=COLORS["success"])
            self.after(2000, lambda: self._overlay_save_btn.configure(
                text="Save Overlay Settings", fg_color=COLORS["accent_primary"]
            ))
        except Exception as e:
            self._overlay_save_btn.configure(text="Error", fg_color=COLORS["error"])
            self.after(2500, lambda: self._overlay_save_btn.configure(
                text="Save Overlay Settings", fg_color=COLORS["accent_primary"]
            ))
            print(f"Error saving overlay settings: {e}")

    def _browse_font_file(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select Custom Font File",
            filetypes=[("TrueType Font", "*.ttf"), ("All files", "*.*")],
        )
        if path:
            self._overlay_font_path_var.set(path)

    def _clear_api_keys(self) -> None:
        for attr, _label, _field in API_KEY_FIELDS:
            entry = getattr(self, f"_entry_{attr}", None)
            if entry is not None:
                entry.delete(0, "end")
        self._save_all_api_keys()

    # ------------------------------------------------------------------
    # Plumbing — let the Voices tab re-fetch after a key change
    # ------------------------------------------------------------------
    def _refresh_voice_frame(self) -> None:
        if not self.app_ref:
            return
        try:
            frames = getattr(self.app_ref, "_frames", None)
            if not frames:
                return
            voice_frame = frames.get("voices")
            if voice_frame is None:
                return
            # If the voice frame exposes a reload hook, use it.
            reload_fn = getattr(voice_frame, "reload_providers", None)
            if callable(reload_fn):
                reload_fn()
        except Exception as e:
            print(f"Could not refresh voice frame after key save: {e}")
