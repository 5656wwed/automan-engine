"""AutoScene Studio CLI — Typer command interface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from app import __app_name__, __version__

cli = typer.Typer(
    name="autoscene",
    help="AutoScene Studio — Cinematic AI Video Generator",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def _version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]{__app_name__}[/] v{__version__}")
        raise typer.Exit()


@cli.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
):
    """AutoScene Studio — Generate cinematic videos from images and scripts."""
    pass


# ---------------------------------------------------------------------------
# RENDER command
# ---------------------------------------------------------------------------
@cli.command()
def render(
    project_file: Path = typer.Argument(
        ...,
        help="Path to the project JSON file.",
        exists=True,
        readable=True,
    ),
    quality: Optional[str] = typer.Option(None, "--quality", "-q", help="Quality preset: low, medium, high, ultra"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Override output path."),
):
    """Render a project into a final cinematic MP4 video."""
    from app.core.config import ExportSettings, QualityPreset
    from app.core.pipeline import RenderPipeline
    from app.core.project import load_project
    from app.utils.logger import setup_logging

    setup_logging(log_dir=project_file.parent / "logs")

    console.print(Panel.fit(
        f"[bold cyan]{__app_name__}[/]\n"
        f"Rendering: [yellow]{project_file.name}[/]",
        border_style="cyan",
    ))

    try:
        project = load_project(project_file)

        export_kwargs = {}
        if quality:
            export_kwargs["quality"] = QualityPreset(quality.lower())

        export = ExportSettings(
            resolution=project.config.resolution,
            fps=project.config.fps,
            **export_kwargs,
        )

        if output:
            project.config.output = str(output)

        pipeline = RenderPipeline(project, export=export)

        # Progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Rendering...", total=100)

            def on_progress(stage: str, scene: int, total: int, pct: float):
                progress.update(task, completed=pct * 100, description=stage)

            pipeline.set_progress_callback(on_progress)
            result = asyncio.run(pipeline.run())

        console.print(f"\n[bold green]✓ Done![/] Output: [underline]{result}[/]")

    except Exception as e:
        # Some exceptions (asyncio.TimeoutError) stringify to "", which made
        # every failed render print a bare "✗ Error:" with no cause.
        msg = str(e).strip()
        console.print(f"\n[bold red]✗ Error:[/] {msg or f'{type(e).__name__} (no message)'}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# CREATE command (alias for render)
# ---------------------------------------------------------------------------
@cli.command()
def create(
    project_file: Path = typer.Argument(..., help="Path to the project JSON file.", exists=True),
):
    """Create a video from a project file (alias for render)."""
    render(project_file=project_file, quality=None, output=None)


# ---------------------------------------------------------------------------
# BATCH command
# ---------------------------------------------------------------------------
@cli.command()
def batch(
    projects_dir: Path = typer.Argument(
        ...,
        help="Directory containing multiple project folders.",
        exists=True,
    ),
):
    """Batch render all projects in a directory."""
    from app.core.pipeline import batch_render
    from app.utils.logger import setup_logging

    setup_logging(log_dir=projects_dir / "logs")

    console.print(Panel.fit(
        f"[bold cyan]{__app_name__} — Batch Mode[/]\n"
        f"Scanning: [yellow]{projects_dir}[/]",
        border_style="cyan",
    ))

    def on_progress(name: str, current: int, total: int):
        console.print(f"  [{current}/{total}] Rendering [yellow]{name}[/]...")

    results = batch_render(projects_dir, progress_callback=on_progress)

    # Summary table
    table = Table(title="Batch Results", border_style="cyan")
    table.add_column("Project", style="bold")
    table.add_column("Status")
    table.add_column("Output")

    for r in results:
        status = "[green]✓ Success[/]" if r["success"] else f"[red]✗ {r['error'][:40]}[/]"
        output = r["output"] or "—"
        table.add_row(r["project"], status, output)

    console.print(table)


# ---------------------------------------------------------------------------
# VOICES command
# ---------------------------------------------------------------------------
@cli.command()
def voices(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Filter by provider."),
):
    """List available TTS voices."""
    from app.tts.voice_manager import VoiceManager

    console.print("[bold cyan]Fetching voices...[/]\n")

    vm = VoiceManager()
    all_voices = asyncio.run(vm.list_all_voices())

    for prov_name, voice_list in all_voices.items():
        if provider and prov_name != provider.lower():
            continue

        table = Table(title=f"{prov_name.upper()} Voices ({len(voice_list)})", border_style="cyan")
        table.add_column("Voice ID", style="bold yellow")
        table.add_column("Name")
        table.add_column("Language")
        table.add_column("Gender")

        for v in voice_list[:30]:  # Show top 30
            table.add_row(v.voice_id, v.name, v.language, v.gender)

        if len(voice_list) > 30:
            table.add_row("...", f"+{len(voice_list) - 30} more", "", "")

        console.print(table)
        console.print()


# ---------------------------------------------------------------------------
# CLONE-VOICE command
# ---------------------------------------------------------------------------
@cli.command("clone-voice")
def clone_voice(
    audio_file: Path = typer.Argument(..., help="Audio sample for voice cloning.", exists=True),
    name: str = typer.Option(..., "--name", "-n", help="Name for the cloned voice."),
    provider: str = typer.Option("elevenlabs", "--provider", "-p", help="TTS provider."),
):
    """Clone a voice from an audio sample."""
    from app.tts.voice_manager import VoiceManager

    console.print(f"[bold cyan]Cloning voice from:[/] {audio_file.name}")

    vm = VoiceManager()
    try:
        voice = asyncio.run(vm.clone_voice(name, audio_file, provider=provider))
        console.print(f"[bold green]✓ Voice cloned![/] ID: [yellow]{voice.voice_id}[/]")
    except Exception as e:
        console.print(f"[bold red]✗ Clone failed:[/] {e}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# PREVIEW-VOICE command
# ---------------------------------------------------------------------------
@cli.command("preview-voice")
def preview_voice(
    text: str = typer.Argument("Hello, this is a voice preview for AutoScene Studio."),
    voice_id: str = typer.Option("en-US-GuyNeural", "--voice", "-v", help="Voice ID."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="TTS provider."),
):
    """Generate a voice preview audio clip."""
    from app.tts.voice_manager import VoiceManager

    console.print(f"[bold cyan]Generating preview...[/] Voice: {voice_id}")

    vm = VoiceManager()
    try:
        path = asyncio.run(vm.preview_voice(voice_id, provider=provider, text=text))
        console.print(f"[bold green]✓ Preview saved:[/] {path}")
    except Exception as e:
        console.print(f"[bold red]✗ Preview failed:[/] {e}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# CHECK-FFMPEG command
# ---------------------------------------------------------------------------
@cli.command("check-ffmpeg")
def check_ffmpeg():
    """Check if FFmpeg is installed and accessible."""
    from app.ffmpeg.detector import INSTALLATION_GUIDE, detect_ffmpeg

    try:
        info = detect_ffmpeg()
        console.print(f"[bold green]✓ FFmpeg found![/]")
        console.print(f"  Path    : {info.path}")
        console.print(f"  Version : {info.version}")
        console.print(f"  libx264 : {'✓' if info.has_libx264 else '✗'}")
        console.print(f"  AAC     : {'✓' if info.has_aac else '✗'}")
    except Exception:
        console.print("[bold red]✗ FFmpeg not found![/]")
        console.print(INSTALLATION_GUIDE)
        raise typer.Exit(code=1)
