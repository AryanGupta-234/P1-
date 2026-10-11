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
    checks = {"native_windows": os.name == "nt",
              "python_311_plus": tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 11)}
    table = Table("Check", "Result")
    for name, ok in checks.items():
        table.add_row(name, "[green]OK[/green]" if ok else "[red]NOT SUPPORTED[/red]")
    console.print(table)
    console.print(f"Local data: {database_path()}")
    if not all(checks.values()):
        raise typer.Exit(1)


@app.command()
def inventory(output: Path | None = typer.Option(None, "--output", "-o")) -> None:
    """Generate a read-only host/process inventory."""
    from aie.providers.windows import WindowsProvider
    result = WindowsProvider().inventory()
    rendered = json.dumps(result, indent=2, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"Inventory saved to {output}")
    else:
        console.print(rendered)


@app.command()
def observe(duration: int = typer.Option(60, min=1, max=86400),
            interval: float = typer.Option(2.0, min=0.5, max=60),
            db: Path = typer.Option(database_path()),
            jsonl: Path | None = typer.Option(None)) -> None:
    """Observe selected Windows metadata (read-only)."""
    from aie.runtime import observe as run_observer
    try:
        added = run_observer(duration, interval, db, jsonl)
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
