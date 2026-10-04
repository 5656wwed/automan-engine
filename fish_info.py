"""List Fish Audio voices the engine can see (requires the API key to be set in
the engine config). Prints JSON:
{"key_set": bool, "voices": [{id,name,is_clone,added}], "extras": [id, ...]}

`extras` are voices pasted on the dashboard (fish_extra_voices in the config) —
usually public/shared models that are not part of the account's own voice list.
Their title is fetched from the Fish Audio API so the dropdown shows a real name.
"""
import asyncio
import json
import urllib.request

from app.core.config import load_config
from app.tts.voice_manager import VoiceManager


def _title(vid: str, key: str) -> str:
    """Ask Fish Audio for the voice's name (best effort, never fatal)."""
    if not key:
        return ""
    try:
        req = urllib.request.Request(f"https://api.fish.audio/model/{vid}",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return (json.load(r).get("title") or "").strip()[:80]
    except Exception:
        return ""


async def main():
    vm = VoiceManager()
    voices = []
    try:
        allv = await vm.list_all_voices()
        voices = allv.get("fishaudio", [])
    except Exception:
        voices = []
    out = [{"id": getattr(v, "id", "") or getattr(v, "voice_id", ""),
            "name": getattr(v, "name", "") or getattr(v, "id", ""),
            "is_clone": bool(getattr(v, "metadata", {}).get("is_clone"))} for v in voices]

    cfg = load_config()
    key = getattr(cfg, "fish_audio_api_key", "") or ""
    extras = [str(x) for x in (getattr(cfg, "fish_extra_voices", None) or []) if str(x).strip()]
    have = {str(v.get("id", "")).lower() for v in out}
    for vid in extras:
        if vid.lower() in have:
            continue
        out.append({"id": vid, "name": _title(vid, key) or vid,
                    "is_clone": False, "added": True})

    print(json.dumps({"key_set": "fishaudio" in vm._providers, "voices": out,
                      "extras": extras}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
