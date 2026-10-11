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


@app.command("uia-windows")
def uia_windows(
    max_windows: int = typer.Option(100, min=1, max=500),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """List visible top-level windows using UIA metadata only (no titles or content)."""
    from aie.automation.uia_inspector import UIAUnavailable, list_top_level_windows

    try:
        windows = list_top_level_windows(max_windows=max_windows)
    except UIAUnavailable as exc:
        console.print(f"[red]UI Automation unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc

    rendered = json.dumps(windows, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"UIA window metadata saved to {output}")
        return

    table = Table("HWND", "PID", "Control", "Class", "Automation ID")
    for window in windows:
        handle = window["handle"]
        table.add_row(
            f"0x{handle:X}" if handle is not None else "N/A",
            str(window["process_id"] or "N/A"),
            window["control_type"] or "N/A",
            window["class_name"] or "N/A",
            window["automation_id"] or "",
        )
    console.print(table)
    console.print(f"Visible windows inspected: {len(windows)}")


@app.command("uia-inspect")
def uia_inspect(
    handle: str = typer.Option(..., "--handle", help="Target HWND in decimal or 0x-prefixed hex."),
    max_depth: int = typer.Option(3, min=0, max=8),
    max_nodes: int = typer.Option(150, min=1, max=1000),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """Inspect a selected window's bounded UIA metadata tree; does not perform actions."""
    from aie.automation.uia_inspector import UIAUnavailable, inspect_window

    try:
        hwnd = int(handle, 0)
    except ValueError as exc:
        raise typer.BadParameter("handle must be decimal or 0x-prefixed hexadecimal") from exc
    try:
        result = inspect_window(hwnd, max_depth=max_depth, max_nodes=max_nodes)
    except (UIAUnavailable, ValueError) as exc:
        console.print(f"[red]UIA inspection unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc

    rendered = json.dumps(result, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"UIA metadata tree saved to {output}")
    else:
        console.print_json(rendered)


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


if __name__ == "__main__":
    app()
