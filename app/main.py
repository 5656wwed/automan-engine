"""AutoScene Studio — Main entry point."""

import sys
import os
from pathlib import Path

# Ensure the project root is on sys.path so `app.*` imports work when
# running via `python -m app.main` or `python app/main.py`.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def init_environment():
    """Inject configuration and dependencies seamlessly."""
    try:
        from app.ffmpeg.detector import detect_ffmpeg
        import traceback
        info = detect_ffmpeg()
        bin_dir = str(Path(info.path).parent)
        # Add to PATH so subprocesses (like pydub) find it
        if bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        
        # Explicit Pydub configuration
        try:
            from pydub import AudioSegment
            AudioSegment.converter = info.path
        except ImportError:
            pass
    except Exception:
        pass


def launch_gui():
    """Launch the desktop GUI application."""
    from app.utils.logger import setup_logging
    from app.core.config import get_config

    config = get_config()
    setup_logging(log_dir=config.cache_dir / "logs")

    from app.gui.app import AutoSceneApp
    app = AutoSceneApp()
    app.mainloop()


def launch_cli():
    """Launch the CLI interface."""
    from app.cli.commands import cli
    cli()


def main():
    """Entry point — launch GUI if no CLI args, otherwise CLI."""
    init_environment()
    if len(sys.argv) > 1:
        launch_cli()
    else:
        launch_gui()


if __name__ == "__main__":
    main()
