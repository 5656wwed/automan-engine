"""Generate a short TTS voice preview for a given provider + voice_id.

Usage: voice_preview.py <provider> <voice_id> [sample_text]
Prints the output audio path on stdout.
"""
import asyncio
import os
import sys
import tempfile

from app.tts.voice_manager import VoiceManager

DEFAULT_TEXT = "Hello! This is a sample of the voice you selected."


async def main(provider: str, voice_id: str, text: str) -> str:
    ext = "wav" if provider == "pocket" else "mp3"
    out = os.path.join(tempfile.gettempdir(), f"voice_preview_{os.getpid()}.{ext}")
    vm = VoiceManager()
    await vm.generate(
        text=text,
        output_path=out,
        provider=provider or None,
        voice_id=voice_id or None,
    )
    return out


if __name__ == "__main__":
    provider = sys.argv[1] if len(sys.argv) > 1 else "edge"
    voice_id = sys.argv[2] if len(sys.argv) > 2 else ""
    text = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else DEFAULT_TEXT
    out = asyncio.run(main(provider, voice_id, text))
    print(out)
