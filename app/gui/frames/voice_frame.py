"""Voice frame — voice selection, preview, and settings."""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

import customtkinter as ctk

from app.core.config import get_config, save_config
from app.gui.theme import COLORS, FONTS, SPACING
from app.tts.voice_manager import VoiceManager


class VoiceFrame(ctk.CTkFrame):
    """Voice selection, preview, and TTS settings panel."""

    def __init__(self, master, app_ref=None, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], corner_radius=0, **kwargs)
        self.app_ref = app_ref
        self._voice_manager: Optional[VoiceManager] = None
        self._voices: dict[str, list] = {}
        # Full set of labels for the *currently selected* provider —
        # used as the source for live filtering as the user types.
        self._all_voice_labels: list[str] = []
        # Guard against the StringVar trace firing while we
        # programmatically set the value (e.g. when populating).
        self._suppress_filter: bool = False
        self._is_loading: bool = False
        self._build_ui()

    def _build_ui(self):
        # Header
        ctk.CTkLabel(
            self, text="🎙 Voices", font=FONTS["heading_lg"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        ctk.CTkLabel(
            self, text="Select TTS provider and configure voice settings",
            font=FONTS["body"], text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", padx=SPACING["lg"], pady=(0, SPACING["md"]))

        # Provider selector card
        prov_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        prov_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            prov_card, text="TTS Provider", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        # Load config to set initial state immediately
        cfg = get_config()
        saved_provider = str(cfg.tts.provider) if cfg.tts.provider else "edge"
        saved_voice_id = cfg.tts.voice_id or "en-US-GuyNeural"
        self._saved_voice_id = cfg.tts.voice_id or ""

        self._provider_var = ctk.StringVar(value=saved_provider)
        self._provider_menu = ctk.CTkOptionMenu(
            prov_card, variable=self._provider_var,
            values=["edge", "elevenlabs", "openai", "ai33pro", "fishaudio", "inworld"],
            fg_color=COLORS["bg_input"], button_color=COLORS["accent_dark"],
            button_hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            command=self._on_provider_change,
            width=200,
        )
        self._provider_menu.pack(side="left", padx=SPACING["md"], pady=(0, SPACING["md"]))

        self._refresh_btn = ctk.CTkButton(
            prov_card, text="🔄 Refresh", font=FONTS["body_sm"],
            fg_color=COLORS["bg_medium"], hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"], corner_radius=6, height=28, width=100,
            command=self.reload_providers,
        )
        self._refresh_btn.pack(side="left", padx=SPACING["sm"], pady=(0, SPACING["md"]))

        # Voice selector card
        voice_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        voice_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            voice_card, text="Voice", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["xs"]))

        self._voice_var = ctk.StringVar(value=saved_voice_id)
        # Searchable combobox — the user can type to filter the list.
        self._voice_menu = ctk.CTkComboBox(
            voice_card, variable=self._voice_var,
            values=["Loading..."],
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            button_color=COLORS["accent_dark"],
            button_hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_text_color=COLORS["text_primary"],
            dropdown_hover_color=COLORS["bg_card_hover"],
            state="normal",  # allow typing
            command=self._on_voice_selected,
            width=420,
        )
        self._voice_menu.pack(padx=SPACING["md"], pady=(0, SPACING["xs"]), anchor="w")

        # Hint just below the combobox
        ctk.CTkLabel(
            voice_card,
            text="💡 Tip: start typing a name or ID to filter the list",
            font=FONTS["body_sm"], text_color=COLORS["text_muted"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["xs"]))

        # Live filter — trace the variable so each keystroke narrows the dropdown.
        self._voice_var.trace_add("write", self._on_voice_text_change)

        self._preview_btn = ctk.CTkButton(
            voice_card, text="▶  Preview Voice", font=FONTS["button"],
            fg_color=COLORS["accent_dark"], hover_color=COLORS["accent_primary"],
            text_color="white", corner_radius=8, height=36,
            command=self._preview_voice,
        )
        self._preview_btn.pack(padx=SPACING["md"], pady=(SPACING["xs"], SPACING["md"]), anchor="w")

        # Fetch by ID section
        fetch_frame = ctk.CTkFrame(voice_card, fg_color="transparent")
        fetch_frame.pack(fill="x", padx=SPACING["md"], pady=(0, SPACING["md"]))
        
        self._fetch_id_var = ctk.StringVar()
        self._fetch_entry = ctk.CTkEntry(
            fetch_frame, textvariable=self._fetch_id_var,
            placeholder_text="Enter hidden Voice ID...",
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            height=32, width=280,
        )
        self._fetch_entry.pack(side="left", padx=(0, SPACING["sm"]))
        
        self._fetch_btn = ctk.CTkButton(
            fetch_frame, text="🔍 Fetch & Add", font=FONTS["body_sm"],
            fg_color=COLORS["bg_medium"], hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"], corner_radius=6, height=32, width=120,
            command=self._fetch_voice_by_id,
        )
        self._fetch_btn.pack(side="left")

        # Voice settings card
        settings_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        settings_card.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

        ctk.CTkLabel(
            settings_card, text="Voice Settings", font=FONTS["heading_sm"],
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=SPACING["md"], pady=(SPACING["md"], SPACING["sm"]))

        # Speed slider
        self._speed_var = ctk.DoubleVar(value=cfg.tts.speed)
        self._add_slider(settings_card, "Speed", self._speed_var, 0.5, 2.0)

        # Pitch slider
        self._pitch_var = ctk.DoubleVar(value=cfg.tts.pitch)
        self._add_slider(settings_card, "Pitch", self._pitch_var, 0.5, 2.0)

        # Stability slider
        self._stability_var = ctk.DoubleVar(value=cfg.tts.stability)
        self._add_slider(settings_card, "Stability", self._stability_var, 0.0, 1.0)

        # Volume slider (0%–200%, default 100%)
        self._volume_var = ctk.DoubleVar(value=cfg.tts.volume)
        self._add_percent_slider(settings_card, "Volume", self._volume_var, 0.0, 2.0)

        # Preset buttons
        preset_frame = ctk.CTkFrame(settings_card, fg_color="transparent")
        preset_frame.pack(fill="x", padx=SPACING["md"], pady=(SPACING["sm"], SPACING["md"]))

        ctk.CTkButton(
            preset_frame, text="💾 Save Preset", font=FONTS["body_sm"],
            fg_color=COLORS["bg_medium"], hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"], corner_radius=6, height=30, width=120,
            command=self._save_preset,
        ).pack(side="left", padx=(0, SPACING["xs"]))

        ctk.CTkButton(
            preset_frame, text="📂 Load Preset", font=FONTS["body_sm"],
            fg_color=COLORS["bg_medium"], hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"], corner_radius=6, height=30, width=120,
            command=self._load_preset,
        ).pack(side="left")

        # Status
        self._status = ctk.CTkLabel(
            self, text="", font=FONTS["body_sm"],
            text_color=COLORS["text_muted"], anchor="w",
        )
        self._status.pack(fill="x", padx=SPACING["lg"], pady=SPACING["sm"])

    def _add_slider(self, parent, label: str, var, from_: float, to_: float):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=SPACING["md"], pady=SPACING["xs"])

        val_label = ctk.CTkLabel(
            frame, text=f"{label}: {var.get():.2f}",
            font=FONTS["body_sm"], text_color=COLORS["text_secondary"], anchor="w", width=120,
        )
        val_label.pack(side="left")

        def on_change(value):
            var.set(round(float(value), 2))
            val_label.configure(text=f"{label}: {var.get():.2f}")

        slider = ctk.CTkSlider(
            frame, from_=from_, to=to_, variable=var,
            fg_color=COLORS["progress_bg"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_light"], button_hover_color=COLORS["accent_primary"],
            command=on_change,
        )
        slider.pack(side="left", fill="x", expand=True, padx=SPACING["sm"])

    def _add_percent_slider(self, parent, label: str, var, from_: float, to_: float):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=SPACING["md"], pady=SPACING["xs"])

        val_label = ctk.CTkLabel(
            frame, text=f"{label}: {int(round(var.get() * 100))}%",
            font=FONTS["body_sm"], text_color=COLORS["text_secondary"], anchor="w", width=120,
        )
        val_label.pack(side="left")

        def on_change(value):
            var.set(round(float(value), 2))
            val_label.configure(text=f"{label}: {int(round(var.get() * 100))}%")

        slider = ctk.CTkSlider(
            frame, from_=from_, to=to_, variable=var,
            fg_color=COLORS["progress_bg"], progress_color=COLORS["accent_primary"],
            button_color=COLORS["accent_light"], button_hover_color=COLORS["accent_primary"],
            command=on_change,
        )
        slider.pack(side="left", fill="x", expand=True, padx=SPACING["sm"])

    def initialize(self):
        """Load voices in background thread if not already loaded."""
        if self._voices or self._is_loading:
            return

        self._voice_manager = VoiceManager()
        self._status.configure(
            text="Loading voices...", text_color=COLORS["text_muted"],
        )
        thread = threading.Thread(target=self._load_voices_async, daemon=True)
        thread.start()

    def reload_providers(self):
        """Re-init the TTS providers and refetch voices.

        Called by the Settings frame after the user saves new API keys
        so that newly enabled providers (e.g. AI33Pro / Minimax) show
        up in the voice picker without restarting the app.
        """
        self._voice_manager = VoiceManager()
        self._voices = {}
        self._all_voice_labels = []
        self._suppress_filter = True
        try:
            self._voice_menu.configure(values=["Loading..."])
            self._voice_var.set("Loading...")
        finally:
            self._suppress_filter = False
        self._status.configure(
            text="Reloading voices with new API keys...",
            text_color=COLORS["text_muted"],
        )
        self._is_loading = True
        thread = threading.Thread(target=self._load_voices_async, daemon=True)
        thread.start()

    def _load_voices_async(self):
        try:
            self._is_loading = True
            loop = asyncio.new_event_loop()
            self._voices = loop.run_until_complete(self._voice_manager.list_all_voices())
            loop.close()
            self.after(0, self._populate_voice_menu)
        except Exception as e:
            self.after(0, lambda: self._status.configure(
                text=f"Failed to load voices: {e}", text_color=COLORS["error"],
            ))
        finally:
            self._is_loading = False

    def _populate_voice_menu(self):
        provider = self._provider_var.get()
        voices = self._voices.get(provider, [])

        if voices:
            # Clones get a 🎤 prefix so the user can spot them at a
            # glance — the provider already sorts clones to the top.
            def _label(v):
                prefix = "🎤 " if v.metadata.get("is_clone") else ""
                return f"{prefix}{v.voice_id} — {v.name}"

            # Cache the full label set; the combobox initially shows
            # all of them, and the trace handler filters this list
            # on every keystroke.
            self._all_voice_labels = [_label(v) for v in voices]

            self._suppress_filter = True
            try:
                self._voice_menu.configure(values=self._all_voice_labels)

                # Restore previously saved voice, or keep current selection
                saved_id = getattr(self, "_saved_voice_id", "")
                current = self._voice_var.get()
                matched = None
                if saved_id:
                    for lbl in self._all_voice_labels:
                        clean = lbl[len("🎤 "):] if lbl.startswith("🎤 ") else lbl
                        if clean.split(" — ")[0] == saved_id:
                            matched = lbl
                            break
                if matched:
                    self._voice_var.set(matched)
                elif current not in self._all_voice_labels and self._all_voice_labels:
                    self._voice_var.set(self._all_voice_labels[0])
            finally:
                self._suppress_filter = False

            clone_count = sum(1 for v in voices if v.metadata.get("is_clone"))
            extra = f" • {clone_count} clone(s)" if clone_count else ""
            self._status.configure(
                text=f"✓ {len(voices)} voices loaded from {provider}{extra} — type to filter",
                text_color=COLORS["success"],
            )
        else:
            self._all_voice_labels = []
            self._suppress_filter = True
            try:
                self._voice_menu.configure(values=["No voices available"])
                self._voice_var.set("No voices available")
            finally:
                self._suppress_filter = False
            self._status.configure(
                text=f"No voices available for {provider}",
                text_color=COLORS["warning"],
            )

    # ------------------------------------------------------------------
    # Live filtering
    # ------------------------------------------------------------------
    def _on_voice_text_change(self, *_args) -> None:
        """Filter the combobox dropdown as the user types.

        Fires on every change of ``_voice_var``. Skips work when we
        ourselves set the value programmatically (``_suppress_filter``)
        or when the user just picked an existing entry from the
        dropdown (in which case the text already matches a full label).
        """
        if self._suppress_filter or not self._all_voice_labels:
            return

        query = self._voice_var.get().strip().lower()

        # If the field is empty, show everything.
        if not query:
            self._voice_menu.configure(values=self._all_voice_labels)
            return

        # If the current text is already one of the cached labels, the
        # user just picked from the dropdown — don't fight the menu.
        if any(query == lbl.lower() for lbl in self._all_voice_labels):
            self._voice_menu.configure(values=self._all_voice_labels)
            return

        # Otherwise, narrow the list to substring matches (case-insensitive),
        # capped at 500 visible entries.
        matches = [
            lbl for lbl in self._all_voice_labels
            if query in lbl.lower()
        ][:500]

        if matches:
            self._voice_menu.configure(values=matches)
        else:
            self._voice_menu.configure(values=["(no matches)"])

    def _fetch_voice_by_id(self):
        voice_id = self._fetch_id_var.get().strip()
        if not voice_id:
            return

        provider = self._provider_var.get()
        self._status.configure(text=f"Searching for '{voice_id}' in {provider}...", text_color=COLORS["accent_primary"])
        self._fetch_btn.configure(state="disabled", text="Searching...")

        def _run():
            try:
                loop = asyncio.new_event_loop()
                voice = loop.run_until_complete(
                    self._voice_manager.get_voice_by_id(voice_id, provider)
                )
                loop.close()

                if voice:
                    # Success! Add to the internal list and refresh UI
                    def _label(v):
                        prefix = "🎤 " if v.metadata.get("is_clone") else ""
                        return f"{prefix}{v.voice_id} — {v.name}"
                    
                    label = _label(voice)
                    if label not in self._all_voice_labels:
                        self._all_voice_labels.insert(0, label)
                        # Also update the _voices cache so it survives provider switches
                        if provider not in self._voices:
                            self._voices[provider] = []
                        self._voices[provider].append(voice)

                    self.after(0, lambda: self._on_fetch_success(label))
                else:
                    self.after(0, lambda: self._on_fetch_fail(f"Voice ID '{voice_id}' not found in {provider}."))

            except Exception as e:
                self.after(0, lambda: self._on_fetch_fail(f"Error fetching voice: {e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_fetch_success(self, label: str):
        self._fetch_btn.configure(state="normal", text="🔍 Fetch & Add")
        self._fetch_id_var.set("")

        self._suppress_filter = True
        try:
            self._voice_menu.configure(values=self._all_voice_labels)
            self._voice_var.set(label)
        finally:
            self._suppress_filter = False

        self._status.configure(text=f"✓ Added: {label}", text_color=COLORS["success"])
        self._persist_voice_selection()

    def _on_fetch_fail(self, error: str):
        self._fetch_btn.configure(state="normal", text="🔍 Fetch & Add")
        self._status.configure(text=error, text_color=COLORS["error"])

    def _persist_voice_selection(self) -> None:
        """Save current provider + voice_id to settings.json."""
        try:
            cfg = get_config()
            cfg.tts.provider = self._provider_var.get()
            cfg.tts.voice_id = self._current_voice_id()
            save_config(cfg)
        except Exception:
            pass

    def _on_voice_selected(self, _choice: str) -> None:
        """Called when the user picks an entry from the dropdown.

        Re-expand the dropdown values back to the full list, so the
        next time the user opens it (without typing) they see everything.
        """
        if self._all_voice_labels:
            self._voice_menu.configure(values=self._all_voice_labels)
        self._persist_voice_selection()

    def _on_provider_change(self, value: str):
        self._populate_voice_menu()

    def _current_voice_id(self) -> str:
        """Extract the bare voice_id from the combobox's current value.

        Label format is ``[🎤 ]<voice_id> — <name>``. If the user typed
        a query and never picked a result, we try to resolve it against
        the cached label list (first substring match wins).
        """
        text = self._voice_var.get().strip()
        if not text or text in ("(no matches)", "No voices available", "Loading..."):
            return ""

        # If it's already a full label, parse normally.
        def _parse(label: str) -> str:
            if label.startswith("🎤 "):
                label = label[len("🎤 "):]
            return label.split(" — ")[0] if " — " in label else label

        if text in self._all_voice_labels:
            return _parse(text)

        # Otherwise, treat it as a search query and pick the first match.
        q = text.lower()
        for lbl in self._all_voice_labels:
            if q in lbl.lower():
                return _parse(lbl)

        # Fallback: assume the user pasted a raw voice_id.
        return _parse(text)

    def _preview_voice(self):
        self._status.configure(text="Generating preview...", text_color=COLORS["accent_primary"])
        voice_id = self._current_voice_id()

        def _run():
            try:
                loop = asyncio.new_event_loop()
                path = loop.run_until_complete(
                    self._voice_manager.preview_voice(
                        voice_id, provider=self._provider_var.get(),
                    )
                )
                loop.close()
                self.after(0, lambda: self._status.configure(
                    text=f"✓ Preview saved: {path}", text_color=COLORS["success"],
                ))
            except Exception as e:
                self.after(0, lambda: self._status.configure(
                    text=f"Preview error: {e}", text_color=COLORS["error"],
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _save_preset(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("Save Preset", "Preset name:")
        if name and self._voice_manager:
            voice_id = self._current_voice_id()
            self._voice_manager.save_preset(name, self._provider_var.get(), voice_id, {
                "speed": self._speed_var.get(),
                "pitch": self._pitch_var.get(),
                "stability": self._stability_var.get(),
                "volume": self._volume_var.get(),
            })
            self._status.configure(text=f"✓ Preset '{name}' saved", text_color=COLORS["success"])

    def _load_preset(self):
        if not self._voice_manager:
            return
        presets = self._voice_manager.list_presets()
        if not presets:
            self._status.configure(text="No presets saved yet", text_color=COLORS["warning"])
            return

        from tkinter import simpledialog
        name = simpledialog.askstring("Load Preset", f"Available: {', '.join(presets.keys())}")
        if name:
            preset = self._voice_manager.load_preset(name)
            if preset:
                self._provider_var.set(preset["provider"])
                self._voice_var.set(preset["voice_id"])
                settings = preset.get("settings", {})
                self._speed_var.set(settings.get("speed", 1.0))
                self._pitch_var.set(settings.get("pitch", 1.0))
                self._stability_var.set(settings.get("stability", 0.5))
                self._volume_var.set(settings.get("volume", 1.0))
                self._status.configure(text=f"✓ Preset '{name}' loaded", text_color=COLORS["success"])

    def get_voice_config(self) -> dict:
        """Get current voice configuration for rendering."""
        voice_id = self._current_voice_id()
        return {
            "provider": self._provider_var.get(),
            "voice_id": voice_id,
            "speed": self._speed_var.get(),
            "pitch": self._pitch_var.get(),
            "stability": self._stability_var.get(),
            "volume": self._volume_var.get(),
        }
