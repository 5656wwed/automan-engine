"""Voice manager — unified voice listing, presets, and provider routing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.core.config import TTSProvider as TTSProviderEnum, get_config
from app.tts.base import TTSProvider, TTSResult, Voice
from app.tts.edge_provider import EdgeTTSProvider
from app.tts.elevenlabs_provider import ElevenLabsProvider
from app.tts.openai_provider import OpenAIProvider
from app.tts.ai33pro_provider import AI33ProProvider
from app.tts.fish_audio_provider import FishAudioProvider
from app.tts.inworld_provider import InworldProvider
from app.utils.logger import get_logger

log = get_logger("tts.manager")


class VoiceManager:
    """Centralized voice/TTS management across all providers."""

    def __init__(self):
        self._providers: dict[str, TTSProvider] = {}
        self._presets_path: Optional[Path] = None
        self._init_providers()

    def _init_providers(self) -> None:
        config = get_config()
        self._presets_path = config.cache_dir / "voice_presets.json"

        # Always register Edge (free)
        self._providers["edge"] = EdgeTTSProvider()

        # Conditionally register paid providers
        el = ElevenLabsProvider()
        if el.is_available():
            self._providers["elevenlabs"] = el

        oai = OpenAIProvider()
        if oai.is_available():
            self._providers["openai"] = oai

        ai33_key = config.ai33pro_api_key
        ai33 = AI33ProProvider(api_key=ai33_key)
        if ai33.is_available():
            self._providers["ai33pro"] = ai33

        fish_key = config.fish_audio_api_key
        fish = FishAudioProvider(api_key=fish_key)
        if fish.is_available():
            self._providers["fishaudio"] = fish

        inworld_key = config.inworld_api_key
        inworld = InworldProvider(
            api_key=inworld_key,
            custom_voices=config.inworld_custom_voices,
        )
        # Always register so premade voices are browsable; generate() will
        # raise if the key is missing when synthesis is actually attempted.
        self._providers["inworld"] = inworld

        log.info(f"Initialized TTS providers: {list(self._providers.keys())}")

    def get_provider(self, name: Optional[str] = None) -> TTSProvider:
        """Get a specific provider or the default one."""
        if name and name in self._providers:
            return self._providers[name]
        
        if name:
            # Provide helpful errors for known providers that aren't configured
            errors = {
                "ai33pro": "AI33Pro API Key not configured. Please set it in Settings.",
                "elevenlabs": "ElevenLabs API Key not configured. Please set it in Settings.",
                "openai": "OpenAI API Key not configured. Please set it in Settings.",
            }
            if name in errors:
                raise RuntimeError(errors[name])

        config = get_config()
        default = config.tts.provider
        if isinstance(default, TTSProviderEnum):
            default = default.value

        if default in self._providers:
            return self._providers[default]

        # Fallback to edge
        if "edge" in self._providers:
            return self._providers["edge"]

        raise RuntimeError("No TTS provider available. Install edge-tts or set API keys.")

    def reload_inworld_voices(self) -> None:
        """Refresh InworldProvider's custom voice list from the latest saved config."""
        config = get_config()
        provider = self._providers.get("inworld")
        if provider is None:
            # API key may have just been added — try registering for the first time
            inworld = InworldProvider(
                api_key=config.inworld_api_key,
                custom_voices=config.inworld_custom_voices,
            )
            if inworld.is_available():
                self._providers["inworld"] = inworld
        else:
            provider.update_custom_voices(config.inworld_custom_voices)

    def get_available_providers(self) -> list[str]:
        """List names of available (configured) providers."""
        return list(self._providers.keys())

    async def list_all_voices(self) -> dict[str, list[Voice]]:
        """List voices from all available providers."""
        result = {}
        for name, provider in self._providers.items():
            try:
                voices = await provider.list_voices()
                result[name] = voices
            except Exception as e:
                log.warning(f"Failed to list voices from {name}: {e}")
                result[name] = []
        return result

    async def get_voice_by_id(self, voice_id: str, provider: Optional[str] = None) -> Optional[Voice]:
        """Fetch a specific voice by its ID, optionally restricted to a provider."""
        if provider:
            prov = self.get_provider(provider)
            return await prov.get_voice(voice_id)
        
        # Search all
        for p_name in self._providers:
            v = await self._providers[p_name].get_voice(voice_id)
            if v:
                return v
        return None

    async def generate(
        self,
        text: str,
        output_path: str | Path,
        provider: Optional[str] = None,
        voice_id: Optional[str] = None,
        **kwargs,
    ) -> TTSResult:
        """Generate speech using the specified or default provider."""
        prov = self.get_provider(provider)
        vid = voice_id or get_config().tts.voice_id

        log.info(f"Generating TTS [{prov.provider_name}] voice={vid}: {text[:60]}...")

        return await prov.generate(
            text=text,
            output_path=output_path,
            voice_id=vid,
            speed=kwargs.get("speed", get_config().tts.speed),
            pitch=kwargs.get("pitch", get_config().tts.pitch),
            stability=kwargs.get("stability", get_config().tts.stability),
            **{k: v for k, v in kwargs.items() if k not in ("speed", "pitch", "stability")},
        )

    async def preview_voice(
        self,
        voice_id: str,
        provider: Optional[str] = None,
        text: str = "Hello, this is a voice preview for AutoScene Studio.",
    ) -> Path:
        """Generate a short preview clip for a voice."""
        prov = self.get_provider(provider)
        return await prov.preview_voice(voice_id, text)

    async def clone_voice(
        self,
        name: str,
        audio_path: str | Path,
        provider: Optional[str] = None,
        description: str = "",
    ) -> Voice:
        """Clone a voice (provider must support it)."""
        prov = self.get_provider(provider or "elevenlabs")
        return await prov.clone_voice(name, audio_path, description)

    # --- Presets ---
    def save_preset(self, name: str, provider: str, voice_id: str, settings: dict) -> None:
        """Save a voice preset for quick reuse."""
        presets = self._load_presets()
        presets[name] = {
            "provider": provider,
            "voice_id": voice_id,
            "settings": settings,
        }
        self._save_presets(presets)
        log.info(f"Saved voice preset: {name}")

    def load_preset(self, name: str) -> Optional[dict]:
        """Load a saved voice preset."""
        presets = self._load_presets()
        return presets.get(name)

    def list_presets(self) -> dict:
        """List all saved presets."""
        return self._load_presets()

    def delete_preset(self, name: str) -> bool:
        presets = self._load_presets()
        if name in presets:
            del presets[name]
            self._save_presets(presets)
            return True
        return False

    def _load_presets(self) -> dict:
        if self._presets_path and self._presets_path.exists():
            with open(self._presets_path, "r") as f:
                return json.load(f)
        return {}

    def _save_presets(self, presets: dict) -> None:
        if self._presets_path:
            self._presets_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._presets_path, "w") as f:
                json.dump(presets, f, indent=2)
