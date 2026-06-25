"""Custom exception classes for AutoScene Studio."""


class AutoSceneError(Exception):
    """Base exception for all AutoScene errors."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}\n  Details: {self.details}"
        return self.message


class FFmpegNotFoundError(AutoSceneError):
    """FFmpeg binary was not found on the system."""

    def __init__(self, searched_paths: list[str] | None = None):
        paths_info = ""
        if searched_paths:
            paths_info = f"Searched: {', '.join(searched_paths)}"
        super().__init__(
            "FFmpeg not found. Please install FFmpeg and add it to your PATH.",
            details=paths_info or "Run 'autoscene check-ffmpeg' for installation instructions.",
        )


class InvalidProjectError(AutoSceneError):
    """Project JSON is invalid or missing required fields."""

    def __init__(self, filepath: str, reason: str):
        super().__init__(
            f"Invalid project file: {filepath}",
            details=reason,
        )


class TTSError(AutoSceneError):
    """Error during text-to-speech generation."""

    def __init__(self, provider: str, message: str, scene_index: int | None = None):
        scene_info = f" (scene {scene_index})" if scene_index is not None else ""
        super().__init__(
            f"TTS error [{provider}]{scene_info}: {message}",
        )


class RenderError(AutoSceneError):
    """Error during video rendering."""

    def __init__(self, stage: str, message: str, scene_index: int | None = None):
        scene_info = f" (scene {scene_index})" if scene_index is not None else ""
        super().__init__(
            f"Render error at {stage}{scene_info}: {message}",
        )


class AudioProcessingError(AutoSceneError):
    """Error during audio processing."""

    def __init__(self, filepath: str, message: str):
        super().__init__(
            f"Audio processing error: {message}",
            details=f"File: {filepath}",
        )


class TransitionError(AutoSceneError):
    """Error applying transition between scenes."""

    def __init__(self, transition_type: str, message: str):
        super().__init__(
            f"Transition error [{transition_type}]: {message}",
        )
