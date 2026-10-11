"""AIE command-line interface."""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aie import __version__
from aie.config import database_path
from aie.hardware import runtime_profile
from aie.model_policy import choose_local_model, discover_local_models
from aie.store import EventStore

app = typer.Typer(no_args_is_help=True, help="AIE Windows-first environment observer.")
console = Console()


@app.command()
def version() -> None:
    """Show AIE version and platform scope."""
    console.print(f"AIE {__version__} | Windows-only")


@app.command()
def doctor() -> None:
    """Check prerequisites without changing the host."""
    checks = {
        "native_windows": os.name == "nt",
        "python_311_plus": tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 11),
    }
    table = Table("Check", "Result")
    for name, ok in checks.items():
        table.add_row(name, "[green]OK[/green]" if ok else "[red]NOT SUPPORTED[/red]")
    console.print(table)
    console.print(f"Local data: {database_path()}")
    if not all(checks.values()):
        raise typer.Exit(1)


@app.command()
def hardware() -> None:
    """Show current resource headroom used by local model policy."""
    console.print_json(json.dumps(runtime_profile(), indent=2))


@app.command()
def models() -> None:
    """Discover installed local Ollama models and show hardware-aware recommendations."""
    installed = discover_local_models()
    profile = runtime_profile()
    memory = profile["memory_available_gib"]
    table = Table("Task", "Selected local model", "Available", "Reason")
    for task in ("routine", "complex", "embedding"):
        decision = choose_local_model(task, installed, memory)
        table.add_row(
            task,
            decision.selected_model or "None",
            "[green]yes[/green]" if decision.available else "[red]no[/red]",
            decision.reason,
        )
    console.print("Ollama endpoint: local only (127.0.0.1 by default)")
    console.print(f"Available memory: {memory:.2f} GiB")
    console.print(table)
    console.print("Installed models:")
    for model in installed:
        console.print(f"  • {model}")
    if not installed:
        console.print("  No local Ollama response. Start Ollama; AIE will not pull models.")


@app.command()
def inventory(output: Path | None = typer.Option(None, "--output", "-o")) -> None:
    """Generate a read-only host, process, app, service, network and task inventory."""
    from aie.providers.windows import WindowsProvider

    try:
        result = WindowsProvider().inventory()
    except OSError as exc:
        console.print(f"[red]Inventory unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc
    rendered = json.dumps(result, indent=2, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"Inventory saved to {output}")
    else:
        console.print(rendered)


@app.command()
def observe(
    duration: int = typer.Option(60, min=1, max=86400),
    interval: float = typer.Option(2.0, min=0.5, max=60),
    db: Path = typer.Option(database_path()),
    jsonl: Path | None = typer.Option(None),
    network: bool = typer.Option(
        True,
        "--network/--no-network",
        help="Include bounded network probes.",
    ),
    network_interval: float = typer.Option(15.0, min=5.0, max=300.0),
    foreground: bool = typer.Option(
        True,
        "--foreground/--no-foreground",
        help="Observe foreground application transitions.",
    ),
    include_window_titles: bool = typer.Option(
        False,
        "--include-window-titles",
        help="Opt in to collecting sensitive foreground window titles.",
    ),
    foreground_sample_interval: float = typer.Option(5.0, min=1.0, max=60.0),
) -> None:
    """Observe selected Windows metadata (read-only)."""
    from aie.runtime import observe as run_observer

    try:
        added = run_observer(
            duration,
            interval,
            db,
            jsonl,
            include_network=network,
            network_interval=network_interval,
            include_foreground=foreground,
            include_window_titles=include_window_titles,
            foreground_sample_interval=foreground_sample_interval,
        )
    except OSError as exc:
        console.print(f"[red]Observer unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Finished: {added} new events stored in {db}")


@app.command()
def events(limit: int = typer.Option(20, min=1, max=1000)) -> None:
    """Display recent normalized observations."""
    store = EventStore(database_path())
    table = Table("Timestamp", "Type", "Entity", "Source")
    for event in store.recent(limit):
        table.add_row(event.timestamp.isoformat(), event.event_type,
                      event.entity.name, event.source)
    console.print(table)
    console.print(f"Total stored: {store.count()}")


@app.command("context")
def show_context(
    max_age_seconds: float = typer.Option(30.0, min=1.0, max=300.0),
) -> None:
    """Show the latest correlated video, foreground-app and network context."""
    from aie.context.video import build_video_observation_context

    store = EventStore(database_path())
    context = build_video_observation_context(
        store.recent(300),
        max_age_seconds=max_age_seconds,
    )
    if context is None:
        console.print(
            "No fresh browser video snapshot is available. "
            "Enable the AIE Playback Observer while a video is playing, "
            "then run this command again."
        )
        return

    table = Table("Signal", "Value")
    table.add_row("Playback", context.playback_state)
    table.add_row("Stall count", str(context.metrics.stall_count))
    table.add_row(
        "Observation window",
        f"{context.metrics.observation_window_seconds:.1f} seconds",
    )
    table.add_row(
        "Buffered ahead",
        "unknown" if context.buffered_ahead_seconds is None
        else f"{context.buffered_ahead_seconds:.2f} seconds",
    )
    table.add_row(
        "Playback progress delta",
        "unknown" if context.playback_progress_delta_seconds is None
        else f"{context.playback_progress_delta_seconds:.2f} seconds",
    )

    if context.active_application is not None:
        app_context = context.active_application
        table.add_row(
            "Foreground app",
            f"{app_context.process_name} (PID {app_context.pid})",
        )
        table.add_row(
            "App CPU",
            "warming up / unavailable" if app_context.cpu_pct is None
            else f"{app_context.cpu_pct:.1f}%",
        )
        table.add_row(
            "App memory",
            "unavailable" if app_context.memory_rss_bytes is None
            else f"{app_context.memory_rss_bytes / (1024 ** 2):.1f} MiB",
        )
        table.add_row(
            "App threads",
            "unavailable" if app_context.thread_count is None
            else str(app_context.thread_count),
        )
        table.add_row("Window title collected", "yes (sensitive)" if app_context.window_title_collected else "no")

    for evidence in context.network_evidence:
        if evidence.kind == "dns_probe":
            value = (
                "unresolved / unavailable"
                if evidence.resolution_ms is None
                else f"{evidence.resolution_ms:.1f} ms"
            )
            table.add_row(f"DNS: {evidence.target}", value)
        else:
            value = (
                "connection failed / unavailable"
                if evidence.connect_latency_ms is None
                else f"{evidence.connect_latency_ms:.1f} ms TCP connect"
            )
            table.add_row(f"Network: {evidence.target}", value)

    console.print(table)
    console.print(
        f"Evidence records: {len(context.evidence_event_ids)} · "
        f"Context age: {(context.generated_at - context.observed_at).total_seconds():.1f}s"
    )


if __name__ == "__main__":
    app()
