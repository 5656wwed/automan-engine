"""Logs frame — real-time scrolling render log viewer."""

from __future__ import annotations

import customtkinter as ctk
from app.gui.theme import COLORS, FONTS, SPACING
from app.utils.logger import register_gui_callback, unregister_gui_callback


class LogsFrame(ctk.CTkFrame):
    """Real-time log viewer with level filtering."""

    def __init__(self, master, app_ref=None, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], corner_radius=0, **kwargs)
        self._all_logs: list[tuple[str, str, str]] = []
        self._build_ui()
        register_gui_callback(self._on_log)

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))
        ctk.CTkLabel(hdr, text="📋 Logs", font=FONTS["heading_lg"],
                     text_color=COLORS["text_primary"]).pack(side="left")

        for txt, cmd in [("📋 Copy", self._copy), ("💾 Export", self._export), ("🗑 Clear", self._clear)]:
            ctk.CTkButton(hdr, text=txt, font=FONTS["body_sm"], fg_color=COLORS["bg_card"],
                          hover_color=COLORS["bg_card_hover"], text_color=COLORS["text_secondary"],
                          corner_radius=6, height=30, width=70, command=cmd).pack(side="right", padx=2)

        flt = ctk.CTkFrame(self, fg_color="transparent")
        flt.pack(fill="x", padx=SPACING["lg"], pady=(0, SPACING["sm"]))
        self._filter = ctk.StringVar(value="ALL")
        for lv in ["ALL", "INFO", "WARNING", "ERROR"]:
            ctk.CTkRadioButton(flt, text=lv, variable=self._filter, value=lv,
                               font=FONTS["body_sm"], fg_color=COLORS["accent_primary"],
                               text_color=COLORS["text_secondary"],
                               command=self._refilter).pack(side="left", padx=SPACING["sm"])

        self._log_box = ctk.CTkTextbox(self, font=FONTS["mono"], fg_color=COLORS["bg_card"],
                                        text_color=COLORS["text_primary"], border_color=COLORS["border"],
                                        border_width=1, corner_radius=8, wrap="word", state="disabled")
        self._log_box.pack(fill="both", expand=True, padx=SPACING["lg"], pady=(0, SPACING["lg"]))

    def _on_log(self, level: str, module: str, message: str):
        # Always update the list (thread-safe append)
        self._all_logs.append((level, module, message))
        
        # Schedule UI update on main thread
        self.after(0, lambda: self._handle_log_ui(level, message))

    def _handle_log_ui(self, level: str, message: str):
        f = self._filter.get()
        if f == "ALL" or level == f:
            self._append(level, message)

    def _append(self, level: str, msg: str):
        icons = {"INFO": "ℹ", "WARNING": "⚠", "ERROR": "✗", "DEBUG": "·"}
        try:
            self._log_box.configure(state="normal")
            self._log_box.insert("end", f" {icons.get(level, '·')} [{level:7s}] {msg}\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
        except Exception:
            pass

    def _refilter(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")
        f = self._filter.get()
        for lv, _, msg in self._all_logs:
            if f == "ALL" or lv == f:
                self._append(lv, msg)

    def _copy(self):
        t = self._log_box.get("1.0", "end").strip()
        if t:
            self.clipboard_clear()
            self.clipboard_append(t)

    def _export(self):
        from tkinter import filedialog
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self._log_box.get("1.0", "end"))

    def _clear(self):
        self._all_logs.clear()
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def destroy(self):
        unregister_gui_callback(self._on_log)
        super().destroy()
