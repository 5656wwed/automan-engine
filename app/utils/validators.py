"""Input validation helpers."""

from __future__ import annotations

from pathlib import Path

# Supported image formats
SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
SUPPORTED_AUDIO_FORMATS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


def is_valid_image(filepath: str | Path) -> bool:
    """Check if a file is a supported image format and exists."""
    p = Path(filepath)
    return p.exists() and p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_FORMATS


def is_valid_audio(filepath: str | Path) -> bool:
    """Check if a file is a supported audio format and exists."""
    p = Path(filepath)
    return p.exists() and p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_FORMATS


def find_images_in_folder(folder: str | Path) -> list[Path]:
    """Find all supported images in a folder, sorted by name."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    images = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_IMAGE_FORMATS
    ]
    return sorted(images, key=lambda p: p.name.lower())


def find_project_folders(base_dir: str | Path) -> list[Path]:
    """Find all subdirectories containing a project.json file (for batch mode)."""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    folders = []
    for item in sorted(base.iterdir()):
        if item.is_dir():
            json_file = item / "project.json"
            if json_file.exists():
                folders.append(item)
    return folders


def validate_resolution(resolution: str) -> tuple[int, int] | None:
    """Validate a resolution string like '1920x1080'. Returns (w, h) or None."""
    try:
        parts = resolution.lower().split("x")
        if len(parts) != 2:
            return None
        w, h = int(parts[0]), int(parts[1])
        if w > 0 and h > 0:
            return (w, h)
    except ValueError:
        pass
    return None
