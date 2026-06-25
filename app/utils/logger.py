"""Structured logging with file + console + GUI-compatible output."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable, Optional

from rich.logging import RichHandler


# ---------------------------------------------------------------------------
# GUI log callback system
# ---------------------------------------------------------------------------
_gui_callbacks: list[Callable[[str, str, str], None]] = []


def register_gui_callback(callback: Callable[[str, str, str], None]) -> None:
    """Register a callback that receives (level, module, message) for GUI display."""
    _gui_callbacks.append(callback)


def unregister_gui_callback(callback: Callable[[str, str, str], None]) -> None:
    """Remove a previously registered GUI callback."""
    if callback in _gui_callbacks:
        _gui_callbacks.remove(callback)


class GUIHandler(logging.Handler):
    """Logging handler that forwards records to registered GUI callbacks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            for cb in _gui_callbacks:
                cb(record.levelname, record.name, msg)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------
_initialized = False


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    log_to_file: bool = True,
) -> None:
    """Initialize application-wide logging."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    root = logging.getLogger("autoscene")
    root.setLevel(level)
    root.propagate = False

    # Rich console handler (pretty terminal output)
    if sys.stdout is not None:
        import io
        from rich.console import Console
        try:
            _console = Console(file=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace"))
        except Exception:
            _console = Console()
        console_handler = RichHandler(
            level=level,
            rich_tracebacks=True,
            show_time=True,
            show_path=False,
            markup=True,
            console=_console,
        )
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(console_handler)

    # File handler
    if log_to_file and log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / "autoscene.log",
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

    # GUI handler (always added, only fires if callbacks registered)
    gui_handler = GUIHandler()
    gui_handler.setLevel(level)
    gui_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(gui_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named child logger under the autoscene namespace."""
    return logging.getLogger(f"autoscene.{name}")
