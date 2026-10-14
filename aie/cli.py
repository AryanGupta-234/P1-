"""AIE command-line interface."""
from __future__ import annotations

import json
import os
import platform
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
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


@app.command("etw-catalog")
def etw_catalog(
    contains: str = typer.Option("Kernel", help="Filter provider names; use an empty string for all."),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """List registered ETW providers without starting or changing a trace session."""
    from aie.providers.etw_catalog import discover_etw_providers, filter_providers

    try:
        providers = filter_providers(discover_etw_providers(), contains)
    except RuntimeError as exc:
        console.print(f"[red]ETW catalog unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc
    rendered = json.dumps(providers, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"Provider catalog saved to {output}")
    else:
        table = Table("Provider", "GUID")
        for provider in providers:
            table.add_row(provider["name"], provider["guid"])
        console.print(table)
    console.print(f"Providers found: {len(providers)}")


@app.command("etw-capture")
def etw_capture(
    output: Path = typer.Argument(..., help="New .etl output path; existing files are never overwritten."),
    duration: int = typer.Option(60, min=1, max=3600, help="Maximum trace duration in seconds."),
) -> None:
    """Opt in to a bounded ETW kernel-process trace; Ctrl+C stops the session."""
    from aie.providers.etw_process import ETWProcessTrace, ETWSessionError

    try:
        with ETWProcessTrace(output) as trace:
            console.print(
                f"ETW session {trace.session_name} active for up to {duration}s. "
                "Press Ctrl+C to stop."
            )
            time.sleep(duration)
    except (ETWSessionError, OSError, ValueError) as exc:
        console.print(f"[red]ETW capture unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"ETW trace saved to {output}")


@app.command("etw-decode")
def etw_decode(
    source_xml: Path = typer.Argument(..., help="XML exported from the ETL file by tracerpt."),
    output: Path = typer.Argument(..., help="New destination JSONL file."),
    db: Path = typer.Option(database_path(), "--db", help="SQLite event store to import into."),
) -> None:
    """Normalize Kernel-Process events into JSONL and the local SQLite store."""
    from aie.providers.etw_decode import decode_trace_xml

    try:
        count = decode_trace_xml(source_xml, output, store=EventStore(db))
    except (OSError, ValueError, ET.ParseError) as exc:
        console.print(f"[red]ETW decode failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Decoded {count} process events to {output} and imported into {db}")


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
    pause_file: Path | None = typer.Option(
        None, help="Pause while this file exists; remove it to resume."
    ),
) -> None:
    """Observe selected Windows metadata (read-only)."""
    from aie.runtime import observe as run_observer

    try:
        added = run_observer(duration, interval, db, jsonl, pause_file)
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


@app.command()
def export_events(output: Path = typer.Argument(...)) -> None:
    """Write the complete event store to a chronological JSONL file."""
    count = EventStore(database_path()).export_jsonl(output)
    console.print(f"Exported {count} events to {output}")


@app.command()
def prune(
    older_than_days: int | None = typer.Option(None, min=1, help="Delete events older than this many days."),
    keep_latest: int | None = typer.Option(None, min=0, help="Keep only the newest N events (0 deletes all)."),
) -> None:
    """Apply one explicit local event-retention policy."""
    if (older_than_days is None) == (keep_latest is None):
        console.print("[red]Choose exactly one: --older-than-days or --keep-latest.[/red]")
        raise typer.Exit(2)
    store = EventStore(database_path())
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        deleted = store.prune(older_than=cutoff)
    else:
        deleted = store.prune(keep_latest=keep_latest)
    console.print(f"Deleted {deleted} events. Remaining: {store.count()}")


if __name__ == "__main__":
    app()
