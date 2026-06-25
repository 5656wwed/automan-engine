"""Auto-pick timestamp/chapter generation for the final video.

The pipeline renders one MP4 per scene, then merges them with FFmpeg
xfade transitions. We can therefore compute the *exact* in-video start
time of each scene as we go (accounting for the transition overlap).

This module turns that per-scene timing into a YouTube-style chapter
list — but **not every scene becomes a chapter**. Instead we pick one
chapter roughly every ``TARGET_CHAPTER_INTERVAL`` seconds. The first
scene always gets a ``00:00`` entry; after that, the first scene whose
start time crosses the next target boundary becomes the next chapter.

Labels are derived from each chosen scene's narration script (first
sentence, trimmed and word-capped) since the JSON has no per-scene
title field filled in for this auto-pick mode.

Output format (matches the user's spec):

    TIMESTAMP:
    00:00 The Reality of Hidden Conspiracies
    03:12 Standing in the Courts of Heaven
    06:08 Exposing Every Secret Agenda
"""

from __future__ import annotations

import asyncio
import re
from typing import Iterable, Optional
import aiohttp

from app.utils.logger import get_logger

log = get_logger("core.timestamps")

# Pick a new chapter roughly every this-many seconds of finished video.
# 180s ≈ the cadence in the user's example (~3 min between chapters).
TARGET_CHAPTER_INTERVAL = 180.0

# Hard caps on the derived chapter label
MAX_LABEL_CHARS = 60
MAX_LABEL_WORDS = 8


def _format_ts(seconds: float) -> str:
    """Format seconds as MM:SS, or HH:MM:SS if the video is >= 1 hour."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _clean_label(text: str) -> str:
    """Strip wrapping punctuation/whitespace and collapse internal spaces."""
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\n\r.!?,;:—–-\"'")


def _derive_label(script: str, fallback: str) -> str:
    """Pull a short, chapter-worthy label out of a scene's narration script.

    Heuristic: take the first complete sentence (split on ``.!?``), then
    cap it at ``MAX_LABEL_WORDS`` words and ``MAX_LABEL_CHARS`` chars.
    Falls back to ``fallback`` if the script is empty.
    """
    script = (script or "").strip()
    if not script:
        return fallback

    # First sentence (rough but good enough for our purposes).
    parts = re.split(r"(?<=[.!?])\s+", script, maxsplit=1)
    first = _clean_label(parts[0] if parts else script)
    if not first:
        return fallback

    # Word cap
    words = first.split()
    if len(words) > MAX_LABEL_WORDS:
        first = " ".join(words[:MAX_LABEL_WORDS]) + "…"

    # Char cap (in case a single "word" is very long)
    if len(first) > MAX_LABEL_CHARS:
        first = first[: MAX_LABEL_CHARS - 1].rstrip() + "…"

    return first


def _scene_start_times(
    durations: Iterable[float],
    transition_duration: float,
) -> list[float]:
    """Return the in-video start time of each scene.

    Mirrors how ``apply_transitions`` overlaps clips: scene 0 starts at
    0, scene i starts at ``sum(durations[:i]) - i * transition_duration``.
    """
    durations = list(durations)
    starts: list[float] = []
    cum = 0.0
    for i, d in enumerate(durations):
        starts.append(cum)
        # Each transition overlaps the next clip with the previous one
        # by ``transition_duration`` seconds.
        cum += d - transition_duration
    return starts


async def _fetch_ai_title(
    session: aiohttp.ClientSession,
    api_key: str,
    segment_text: str,
    fallback_label: str,
) -> str:
    """Fetch a concise, dramatic chapter title from Groq for the given script segment.

    Falls back to fallback_label on error or timeout.
    """
    segment_text = (segment_text or "").strip()
    if not segment_text:
        return fallback_label

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    prompt = (
        "You are an expert documentary video editor and writer.\n"
        "Generate a concise, dramatic chapter title for the following segment of the script narration.\n"
        "Rules:\n"
        "1. Do not use quotes or introductory/explanatory text. Return ONLY the title.\n"
        "2. The title must be dynamic, punchy, and match a dramatic history/documentary tone.\n"
        "3. The title must be in Title Case and no longer than 5 to 6 words.\n\n"
        f"Script text:\n{segment_text}"
    )

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.5,
        "max_tokens": 30
    }

    try:
        async with session.post(url, headers=headers, json=payload, timeout=8.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                title = data["choices"][0]["message"]["content"].strip()
                # Clean up formatting: strip common prefixes
                for prefix in ["chapter title:", "title:", "here is a title:", "here is the title:", "chapter:"]:
                    if title.lower().startswith(prefix):
                        title = title[len(prefix):].strip()
                title = title.strip(" \t\n\r.\"'“”‘’")
                if title and not title.lower().startswith("here is a") and "\n" not in title:
                    return title
            else:
                log.warning(f"Groq API returned status {resp.status}")
    except Exception as e:
        log.warning(f"Failed to fetch AI title from Groq: {e}")

    return fallback_label


async def build_timestamps_content(
    scenes,
    durations: list[float],
    transition_duration: float,
    target_interval: float = TARGET_CHAPTER_INTERVAL,
) -> Optional[str]:
    """Build the full text body of timestamps.txt, or ``None`` if empty.

    Args:
        scenes: Iterable of SceneConfig (or anything with ``.script``
            and optional ``.title``).
        durations: Per-scene render duration in seconds (same length
            as ``scenes``).
        transition_duration: The xfade overlap between consecutive
            clips. Subtracted once per transition when computing the
            cumulative timeline.
        target_interval: Seconds between auto-picked chapters.

    Selection rule:
        * If any scene already has a non-empty ``title``, those titled
          scenes become the chapters (manual override mode).
        * Otherwise, walk the timeline and pick the first scene that
          crosses each ``target_interval`` boundary — starting at 0.
        * For each chosen scene boundary, we group all scene scripts
          belonging to that chapter block, and fetch a title using Groq.
    """
    scenes = list(scenes)
    if not scenes:
        return None

    starts = _scene_start_times(durations, transition_duration)
    # Defensive: pad starts so we can zip even if lengths mismatch.
    if len(starts) < len(scenes):
        starts.extend([starts[-1] if starts else 0.0] * (len(scenes) - len(starts)))

    # ── Manual override: if any scene has an explicit title, use those
    manual_titles = [getattr(s, "title", None) for s in scenes]
    if any(t for t in manual_titles):
        lines = ["TIMESTAMP:"]
        for s, start, t in zip(scenes, starts, manual_titles):
            if t:
                lines.append(f"{_format_ts(start)} {_clean_label(t)}")
        return "\n".join(lines) if len(lines) > 1 else None

    # ── Auto-pick mode
    chosen_indices = []
    last_chapter_time = -target_interval

    for idx, (scene, start) in enumerate(zip(scenes, starts)):
        if start + 1e-6 >= last_chapter_time + target_interval:
            chosen_indices.append(idx)
            last_chapter_time = start

    if not chosen_indices:
        return None

    # Get Groq API key
    import os
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        try:
            from app.core.config import get_config
            api_key = get_config().groq_api_key
        except Exception:
            pass

    if api_key:
        api_key = api_key.strip()
        if api_key in ("", "None"):
            api_key = None

    labels = []
    if api_key:
        log.info("Generating AI chapter titles using Groq API...")
        tasks = []
        async with aiohttp.ClientSession() as session:
            for k, idx in enumerate(chosen_indices):
                # Build fallback label
                fallback_label = _derive_label(
                    getattr(scenes[idx], "script", "") or "",
                    fallback=f"Chapter {k + 1}",
                )
                
                # Gather script block text
                end_idx = chosen_indices[k+1] if k + 1 < len(chosen_indices) else len(scenes)
                block_scenes = scenes[idx:end_idx]
                block_text = " ".join([getattr(s, "script", "") or "" for s in block_scenes]).strip()
                
                tasks.append(_fetch_ai_title(session, api_key, block_text, fallback_label))
            
            labels = await asyncio.gather(*tasks)
    else:
        log.info("No Groq API key configured. Falling back to heuristic-based chapter titles.")
        for k, idx in enumerate(chosen_indices):
            label = _derive_label(
                getattr(scenes[idx], "script", "") or "",
                fallback=f"Chapter {k + 1}",
            )
            labels.append(label)

    lines = ["TIMESTAMP:"]
    for idx, label in zip(chosen_indices, labels):
        start = starts[idx]
        lines.append(f"{_format_ts(start)} {label}")
    return "\n".join(lines)
