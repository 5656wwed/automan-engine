"""Automatic pronunciation + script cleaner for TTS.

Applied to every narration line just before the voice runs, so tricky names
and symbols are spoken correctly WITHOUT touching the original script text
(overlays/subtitles keep the real spelling).

Persistent dictionary: theautoman/pronunciation_map.json
  format: { "Original Name": "how-it-should-SOUND" }
Add a line to that file once and every future script is fixed automatically.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "pronunciation_map.json"

# ---------------------------------------------------------------------------
# Pronunciation dictionary (from JSON, word-boundary, case-insensitive)
# ---------------------------------------------------------------------------
def _load_map() -> dict[str, str]:
    try:
        with open(_MAP_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k and v}
    except Exception:
        return {}


def apply_pronunciation_map(text: str) -> str:
    """Replace every dictionary key (as a whole word) with its phonetic value."""
    for name, phonetic in _load_map().items():
        pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
        text = re.sub(pattern, phonetic, text, flags=re.IGNORECASE)
    return text


def pronunciation_version() -> str:
    """Hash of the dictionary — appended to the render cache key so editing the
    dictionary forces scenes to re-render with the new pronunciation."""
    try:
        return hashlib.md5(_MAP_PATH.read_bytes()).hexdigest()[:8]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Script cleanser (Roman numerals, eras, symbols, rhythm)
# ---------------------------------------------------------------------------
_ROMAN = {
    "XIV": "the Fourteenth",
    "XVI": "the Sixteenth",
    "VIII": "the Eighth",
    "XIII": "the Thirteenth",
    "XII": "the Twelfth",
    "XV": "the Fifteenth",
    "XI": "the Eleventh",
    "III": "the Third",
    "VII": "the Seventh",
    "IV": "the Fourth",
    "IX": "the Ninth",
    "VI": "the Sixth",
    "II": "the Second",
    "V": "the Fifth",
    "X": "the Tenth",
    "I": "the First",
}
# longest-first so "VIII" isn't caught by "VI" + "II"
_ROMAN_ALT = "|".join(sorted(_ROMAN, key=len, reverse=True))

_ERA = [
    (r"\bB\.?C\.?E\.?\b", "B C E"),
    (r"\bC\.?E\.?\b", "C E"),
    (r"\bB\.?C\.?\b", "B C"),
    (r"\bA\.?D\.?\b", "A D"),
]

_SYMBOLS = [
    (r"%", " percent"),
    (r"\$", "dollars "),
    (r"&", "and"),
    (r"\s*--\s*|\s*—\s*", "... "),
]

_DECADE_SUFFIX = {
    10: "tens", 20: "twenties", 30: "thirties", 40: "forties", 50: "fifties",
    60: "sixties", 70: "seventies", 80: "eighties", 90: "nineties",
}


def _fix_decades(text: str) -> str:
    """Turn '1980s'/'2020s' into 'nineteen eighties' / 'twenty twenties'."""
    try:
        from num2words import num2words
    except Exception:
        return text

    def repl(m: re.Match) -> str:
        year = int(m.group(0)[:-1])  # drop trailing 's'
        century, dec = year // 100, year % 100
        cent_word = num2words(century, to="cardinal")
        return f"{cent_word} {_DECADE_SUFFIX.get(dec, str(dec))}"

    return re.sub(r"\b(1[5-9]|20)\d0s\b", repl, text)


def clean_for_tts(text: str) -> str:
    """Normalize everything a TTS typically stumbles over, in one pass."""
    text = apply_pronunciation_map(text)

    # Roman numerals following a capitalized word (Henry VIII -> Henry the Eighth)
    text = re.sub(
        r"\b([A-Z][a-z]{2,})\s(" + _ROMAN_ALT + r")\b",
        lambda m: f"{m.group(1)} {_ROMAN[m.group(2)]}",
        text,
    )

    for pat, rep in _ERA:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)

    for pat, rep in _SYMBOLS:
        text = re.sub(pat, rep, text)

    # years/decades: "1980s" -> "nineteen eighties"
    text = _fix_decades(text)

    # Collapse any double spaces left behind
    return re.sub(r" {2,}", " ", text).strip()
