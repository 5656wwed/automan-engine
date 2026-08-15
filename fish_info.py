"""List Fish Audio voices the engine can see (requires the API key to be set in
the engine config). Prints JSON: {"key_set": bool, "voices": [{id,name,is_clone}]}
"""
import asyncio
import json

from app.tts.voice_manager import VoiceManager


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
    print(json.dumps({"key_set": "fishaudio" in vm._providers, "voices": out}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
