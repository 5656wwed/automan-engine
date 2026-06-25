"""AutoScene Studio — Dark theme design system."""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════
# COLOR PALETTE — Deep Navy / Cyan Accent
# ═══════════════════════════════════════════════════════════════════
COLORS = {
    # Backgrounds
    "bg_darkest":       "#0a0e17",
    "bg_dark":          "#0f1523",
    "bg_medium":        "#151c2e",
    "bg_card":          "#1a2238",
    "bg_card_hover":    "#1f2940",
    "bg_input":         "#111827",

    # Accent
    "accent_primary":   "#06b6d4",   # Cyan-500
    "accent_light":     "#22d3ee",   # Cyan-400
    "accent_dark":      "#0891b2",   # Cyan-600
    "accent_glow":      "#06b6d420", # Cyan with alpha

    # Secondary accent
    "purple":           "#8b5cf6",
    "purple_light":     "#a78bfa",

    # Status
    "success":          "#10b981",
    "warning":          "#f59e0b",
    "error":            "#ef4444",
    "info":             "#3b82f6",

    # Text
    "text_primary":     "#f1f5f9",
    "text_secondary":   "#94a3b8",
    "text_muted":       "#64748b",
    "text_accent":      "#22d3ee",

    # Borders
    "border":           "#1e293b",
    "border_hover":     "#334155",
    "border_accent":    "#06b6d4",

    # Misc
    "scrollbar":        "#334155",
    "progress_bg":      "#1e293b",
    "progress_fill":    "#06b6d4",
}

# ═══════════════════════════════════════════════════════════════════
# TYPOGRAPHY
# ═══════════════════════════════════════════════════════════════════
FONTS = {
    "heading_xl":   ("Segoe UI", 28, "bold"),
    "heading_lg":   ("Segoe UI", 22, "bold"),
    "heading_md":   ("Segoe UI", 18, "bold"),
    "heading_sm":   ("Segoe UI", 14, "bold"),
    "body":         ("Segoe UI", 13),
    "body_sm":      ("Segoe UI", 11),
    "mono":         ("Cascadia Code", 12),
    "mono_sm":      ("Cascadia Code", 10),
    "button":       ("Segoe UI", 13, "bold"),
    "label":        ("Segoe UI", 12),
    "nav":          ("Segoe UI", 13, "bold"),
}

# ═══════════════════════════════════════════════════════════════════
# SPACING & DIMENSIONS
# ═══════════════════════════════════════════════════════════════════
SPACING = {
    "xs":   4,
    "sm":   8,
    "md":   16,
    "lg":   24,
    "xl":   32,
    "xxl":  48,
}

DIMENSIONS = {
    "sidebar_width":    220,
    "card_radius":      12,
    "button_radius":    8,
    "input_height":     38,
    "window_width":     1280,
    "window_height":    800,
    "min_width":        960,
    "min_height":       600,
}

# ═══════════════════════════════════════════════════════════════════
# NAVIGATION ITEMS
# ═══════════════════════════════════════════════════════════════════
NAV_ITEMS = [
    {"id": "project",  "label": "📁  Project",   "icon": "📁"},
    {"id": "voices",   "label": "🎙  Voices",    "icon": "🎙"},
    {"id": "render",   "label": "🎬  Render",    "icon": "🎬"},
    {"id": "settings", "label": "⚙  Settings",  "icon": "⚙"},
    {"id": "logs",     "label": "📋  Logs",      "icon": "📋"},
]
