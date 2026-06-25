"""Render cache manager — hash-based audio caching to skip regeneration."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional

from app.core.config import get_config
from app.utils.logger import get_logger

log = get_logger("utils.cache")


class CacheManager:
    """Hash-based caching for generated audio and rendered clips."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or get_config().cache_dir
        self.audio_cache = self.cache_dir / "audio"
        self.audio_cache.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.cache_dir / "cache_manifest.json"
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        if self._manifest_path.exists():
            try:
                with open(self._manifest_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_manifest(self) -> None:
        with open(self._manifest_path, "w") as f:
            json.dump(self._manifest, f, indent=2)

    @staticmethod
    def compute_hash(text: str, voice_id: str, **settings) -> str:
        """Compute a deterministic hash for a TTS generation request."""
        payload = json.dumps({
            "text": text,
            "voice_id": voice_id,
            **{k: str(v) for k, v in sorted(settings.items())},
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def get_cached_audio(self, cache_key: str) -> Optional[Path]:
        """Check if cached audio exists for a given cache key."""
        if cache_key in self._manifest:
            cached_path = Path(self._manifest[cache_key]["path"])
            if cached_path.exists():
                log.debug(f"Cache hit: {cache_key}")
                return cached_path
            else:
                # Stale entry
                del self._manifest[cache_key]
                self._save_manifest()
        return None

    def store_audio(self, cache_key: str, source_path: Path, text: str = "") -> Path:
        """Copy generated audio into the cache."""
        ext = source_path.suffix or ".mp3"
        cached_path = self.audio_cache / f"{cache_key}{ext}"
        shutil.copy2(source_path, cached_path)

        self._manifest[cache_key] = {
            "path": str(cached_path),
            "text_preview": text[:100],
        }
        self._save_manifest()
        log.debug(f"Cached audio: {cache_key}")
        return cached_path

    def clear_cache(self) -> int:
        """Clear all cached files. Returns number of files removed."""
        count = 0
        if self.audio_cache.exists():
            for f in self.audio_cache.iterdir():
                if f.is_file():
                    f.unlink()
                    count += 1
        self._manifest = {}
        self._save_manifest()
        log.info(f"Cache cleared: {count} files removed.")
        return count

    def get_cache_size_mb(self) -> float:
        """Get total cache size in megabytes."""
        total = 0
        if self.audio_cache.exists():
            for f in self.audio_cache.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return total / (1024 * 1024)

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "entries": len(self._manifest),
            "size_mb": round(self.get_cache_size_mb(), 2),
            "path": str(self.cache_dir),
        }
