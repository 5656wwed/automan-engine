"""CapCut-style color grading helpers.

Builds an ffmpeg filter chain from a 3D LUT (.cube) + adjustments:
  lut3d=<blended.cube>,eq=brightness=..:contrast=..:saturation=..,colortemperature=temperature=..

"Intensity" is handled by pre-blending the LUT toward identity (no ffmpeg blend
filter_complex needed), so the whole chain stays a single -vf string.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

LUTS_DIR = Path(__file__).resolve().parent.parent.parent / "luts"

# Defaults (neutral)
DEFAULTS = {
    "intensity": 1.0,
    "brightness": 0.0,   # eq brightness, -1..1
    "contrast": 1.0,     # eq contrast, 0..2 (1 = neutral)
    "saturation": 1.0,   # eq saturation, 0..3 (1 = neutral)
    "warmth": 0.0,       # -1..1  -> +warm (orange) / -cool (blue)
}


def resolve_lut(name: str) -> Path | None:
    if not name:
        return None
    for candidate in (LUTS_DIR / name, LUTS_DIR / f"{name}.cube"):
        if candidate.exists():
            return candidate
    low = name.lower()
    for f in LUTS_DIR.glob("*.cube"):
        if f.stem.lower() == low:
            return f
    return None


def blend_lut(src: Path, intensity: float, out: Path) -> Path:
    """Write a .cube that is `src` blended toward identity by `intensity`."""
    intensity = max(0.0, min(1.0, intensity))
    if intensity >= 1.0:
        shutil.copyfile(src, out)
        return out
    lines = src.read_text(encoding="utf-8").splitlines()
    with open(out, "w", encoding="utf-8") as f:
        size = None
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                f.write(line + "\n")
                continue
            if s.upper().startswith("LUT_3D_SIZE"):
                size = int(s.split()[-1])
                f.write(line + "\n")
                continue
            if s.upper().startswith("DOMAIN"):
                f.write(line + "\n")
                continue
            parts = s.split()
            if len(parts) == 3:
                try:
                    r, g, b = (float(x) for x in parts)
                except ValueError:
                    f.write(line + "\n")
                    continue
                n = size or 33
                coord = (r * (n - 1), g * (n - 1), b * (n - 1))
                cx, cy, cz = (c / (n - 1) for c in coord)
                r = r * intensity + cx * (1 - intensity)
                g = g * intensity + cy * (1 - intensity)
                b = b * intensity + cz * (1 - intensity)
                f.write(f"{r:.5f} {g:.5f} {b:.5f}\n")
            else:
                f.write(line + "\n")
    return out


def build_color_chain(
    color_filter: str | None = None,
    intensity: float | None = None,
    brightness: float | None = None,
    contrast: float | None = None,
    saturation: float | None = None,
    warmth: float | None = None,
) -> str | None:
    """Return an ffmpeg -vf string for the chosen LUT + adjustments, or None."""
    intensity = DEFAULTS["intensity"] if intensity is None else float(intensity)
    brightness = DEFAULTS["brightness"] if brightness is None else float(brightness)
    contrast = DEFAULTS["contrast"] if contrast is None else float(contrast)
    saturation = DEFAULTS["saturation"] if saturation is None else float(saturation)
    warmth = DEFAULTS["warmth"] if warmth is None else float(warmth)

    chain: list[str] = []

    lut = resolve_lut(color_filter) if color_filter else None
    if lut:
        tmpdir = Path(tempfile.gettempdir()) / "automan_luts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        blended = tmpdir / f"{lut.stem}_i{int(intensity*100)}.cube"
        if not blended.exists():
            blend_lut(lut, intensity, blended)
        lut_esc = str(blended).replace("\\", "/").replace(":", "\\:")
        chain.append(f"lut3d={lut_esc}")

    # eq adjustments (only add if non-neutral)
    eq = f"eq=brightness={brightness:.2f}:contrast={contrast:.2f}:saturation={saturation:.2f}"
    if brightness or contrast != 1.0 or saturation != 1.0:
        chain.append(eq)

    # warmth via colortemperature (6500 = neutral)
    if warmth:
        temp = int(6500 - warmth * 2000)
        chain.append(f"colortemperature=temperature={temp}")

    if not chain:
        return None
    return ",".join(chain)
