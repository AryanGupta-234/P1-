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


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Text prompt sent only to the selected local model."),
    task: str = typer.Option("routine", help="Model policy: routine or complex."),
    timeout: float = typer.Option(60.0, min=1.0, max=300.0),
) -> None:
    """Run one bounded, non-streaming chat request against a selected local Ollama model."""
    from aie.ollama import OllamaClient, OllamaError
    from aie.model_policy import choose_local_model

    if task not in {"routine", "complex"}:
        raise typer.BadParameter("task must be routine or complex")
    installed = discover_local_models()
    memory = runtime_profile()["memory_available_gib"]
    decision = choose_local_model(task, installed, memory)
    if not decision.available or decision.selected_model is None:
        console.print(f"[yellow]No eligible local model:[/yellow] {decision.reason}")
        raise typer.Exit(2)
    try:
        result = OllamaClient(timeout=timeout).chat(
            decision.selected_model,
            [{"role": "user", "content": prompt}],
        )
    except (OllamaError, ValueError) as exc:
        console.print(f"[red]Local inference failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(result.content)


@app.command()
def embed(
    text: str = typer.Argument(..., help="Text sent only to the local embedding model."),
    expected_dimensions: int | None = typer.Option(None, min=1),
    timeout: float = typer.Option(60.0, min=1.0, max=300.0),
) -> None:
    """Check local embedding inference and report dimensions without printing vectors."""
    from aie.ollama import OllamaClient, OllamaError

    installed = discover_local_models()
    decision = choose_local_model("embedding", installed)
    if not decision.available or decision.selected_model is None:
        console.print("[yellow]No eligible local embedding model is installed.[/yellow]")
        raise typer.Exit(2)
    try:
        result = OllamaClient(timeout=timeout).embed(
            decision.selected_model,
            text,
            expected_dimensions=expected_dimensions,
        )
    except (OllamaError, ValueError) as exc:
        console.print(f"[red]Local embedding failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(
        f"Model: {result.model} | dimensions: {result.dimensions} | vectors: 1"
    )


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
    from aie.providers.etw_decode import decode_trace_xml, read_trace_stats

    try:
        stats = read_trace_stats(source_xml)
        count = decode_trace_xml(source_xml, output, store=EventStore(db))
    except (OSError, ValueError, ET.ParseError) as exc:
        console.print(f"[red]ETW decode failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Decoded {count} process events to {output} and imported into {db}")
    if stats.events_lost is not None:
        style = "yellow" if stats.events_lost else "green"
        console.print(f"[{style}]ETW events lost: {stats.events_lost}[/{style}]")
    else:
        console.print("ETW loss counters were not present in this tracerpt XML.")


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
def correlate(
    since_minutes: int = typer.Option(1440, min=1, max=10080, help="Look back up to seven days."),
    limit: int = typer.Option(10000, min=1, max=10000, help="Maximum source events to inspect."),
    db: Path = typer.Option(database_path(), "--db", help="SQLite event store."),
) -> None:
    """Correlate ETW process starts with matching user-mode process snapshots."""
    from aie.correlation import correlate_process_starts

    store = EventStore(db)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    source_events = store.events_since(cutoff, limit=limit)
    derived = correlate_process_starts(source_events)
    inserted = store.append_many(derived)
    console.print(
        f"Inspected {len(source_events)} source events; "
        f"derived {len(derived)} process-start confirmations; "
        f"stored {inserted} new events."
    )


@app.command()
def context(db: Path = typer.Option(database_path(), "--db")) -> None:
    """Show a bounded factual context packet from the latest saved projection."""
    from aie.context import build_environment_context
    from aie.state_model import EnvironmentProjection

    try:
        saved = EventStore(db).load_state_snapshot("aie.environment.v1")
    except ValueError as exc:
        console.print(f"[red]Saved projection integrity check failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    if saved is None:
        console.print("No saved projection. Run aie state first.")
        raise typer.Exit(2)
    version, _, payload = saved
    if version != 1:
        raise typer.Exit(2)
    projection = EnvironmentProjection.from_dict(json.loads(payload))
    packet = build_environment_context(projection)
    console.print_json(json.dumps(packet, default=str))


@app.command()
def state(
    limit: int = typer.Option(
        10000, min=1, max=10000, help="Maximum new events to process per invocation."
    ),
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Replay all currently retained events from the beginning."
    ),
    recover: bool = typer.Option(
        False, "--recover", help="Recover from a missing or corrupt snapshot using the previous verified generation."
    ),
    db: Path = typer.Option(database_path(), "--db", help="SQLite event store."),
) -> None:
    """Update and display the durable evidence-backed environment projection."""
    from dataclasses import asdict
    from aie.state_model import EnvironmentProjection, project_environment_state

    store = EventStore(db)
    if rebuild and recover:
        raise typer.BadParameter("--rebuild and --recover cannot be used together")
    try:
        snapshot = None if rebuild else store.load_state_snapshot("aie.environment.v1")
    except ValueError as exc:
        if not recover:
            console.print(
                f"[red]Saved projection failed integrity verification:[/red] {exc} "
                "Use --recover to restore the previous verified snapshot, or --rebuild."
            )
            raise typer.Exit(2) from exc
        try:
            snapshot = store.restore_state_snapshot_backup("aie.environment.v1")
        except ValueError as backup_exc:
            console.print(f"[red]Snapshot backup is also invalid:[/red] {backup_exc}")
            raise typer.Exit(2) from backup_exc
        if snapshot is None:
            console.print("[red]No previous verified snapshot is available to recover.[/red]")
            raise typer.Exit(2)
        console.print("[yellow]Restored previous verified snapshot; replaying later events.[/yellow]")
    else:
        if recover and snapshot is None:
            snapshot = store.restore_state_snapshot_backup("aie.environment.v1")
            if snapshot is None:
                console.print("[red]No previous verified snapshot is available to recover.[/red]")
                raise typer.Exit(2)
            console.print("[yellow]Restored previous verified snapshot; replaying later events.[/yellow]")
    if snapshot is None:
        projection = None
        watermark = 0
    else:
        version, watermark, payload = snapshot
        if version != 1:
            console.print("[red]Unsupported environment snapshot version; use --rebuild.[/red]")
            raise typer.Exit(2)
        try:
            projection = EnvironmentProjection.from_dict(json.loads(payload))
        except (ValueError, TypeError, KeyError) as exc:
            console.print(f"[red]Saved projection is invalid; use --rebuild:[/red] {exc}")
            raise typer.Exit(2) from exc

    batch = store.events_after_sequence(watermark, limit=limit)
    projection = project_environment_state(
        (event for _, event in batch), initial=projection
    )
    if batch:
        watermark = batch[-1][0]
    try:
        store.save_state_snapshot(
            "aie.environment.v1", watermark,
            json.dumps(projection.to_dict(), separators=(",", ":"), allow_nan=False),
            schema_version=1,
        )
    except ValueError as exc:
        console.print(f"[red]Projection snapshot was not saved:[/red] {exc}")
        raise typer.Exit(2) from exc
    pending = bool(store.events_after_sequence(watermark, limit=1))
    result = {
        "projection_version": 1,
        "last_ingest_sequence": watermark,
        "new_events_processed": len(batch),
        "more_events_pending": pending,
        "coverage": projection.coverage,
        "processes": [asdict(item) for _, item in sorted(projection.processes.items())],
        "entities": [asdict(item) for _, item in sorted(projection.entities.items())],
        "ignored_events": projection.ignored_events,
        "limitations": [
            "Projection includes evidence ingested up to the reported SQLite ingestion sequence.",
            "The initial process baseline contains a count only; pre-existing instances remain unknown.",
            "Pruned evidence cannot be reconstructed by --rebuild.",
            "Missing entities are never inferred to be removed; only explicit removal evidence changes status.",
        ],
    }
    console.print_json(json.dumps(result, default=str))


@app.command("uia-inspect")
def uia_inspect(
    max_windows: int = typer.Option(12, min=1, max=40),
    max_nodes: int = typer.Option(250, min=1, max=1000),
    max_depth: int = typer.Option(5, min=1, max=8),
    timeout: float = typer.Option(12.0, min=1.0, max=30.0),
) -> None:
    """Inspect UI Automation control structure only; never reads field text or acts."""
    from dataclasses import asdict
    from aie.providers.uia import inspect_windows

    try:
        result = inspect_windows(
            max_windows=max_windows, max_nodes=max_nodes,
            max_depth=max_depth, timeout=timeout,
        )
    except ValueError as exc:
        console.print(f"[red]UIA inspection rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(asdict(result), indent=2))
    if not result.available:
        raise typer.Exit(2)


@app.command("compact-state")
def compact_state(
    older_than_days: int = typer.Option(90, min=1, max=36500, help="Only terminal records older than this age are eligible."),
    max_terminal_records: int = typer.Option(1000, min=0, max=10000, help="Retain this many newest eligible terminal records per collection."),
    db: Path = typer.Option(database_path(), "--db", help="SQLite event store."),
) -> None:
    """Explicitly compact old terminal projection records without deleting raw events."""
    from aie.state_compaction import compact_projection
    from aie.state_model import EnvironmentProjection

    store = EventStore(db)
    try:
        saved = store.load_state_snapshot("aie.environment.v1")
        if saved is None:
            raise ValueError("no saved projection; run aie state first")
        version, watermark, payload = saved
        if version != 1:
            raise ValueError("unsupported projection version")
        projection = EnvironmentProjection.from_dict(json.loads(payload))
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        result = compact_projection(
            projection, older_than=cutoff, max_terminal_records=max_terminal_records
        )
        serialized = json.dumps(result.projection.to_dict(), separators=(",", ":"), allow_nan=False)
        store.save_state_snapshot("aie.environment.v1", watermark, serialized, schema_version=1)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        console.print(f"[red]State compaction failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps({
        "processes_removed": result.processes_removed,
        "entities_removed": result.entities_removed,
        "max_terminal_records": result.max_terminal_records,
        "cutoff": cutoff.isoformat(),
        "last_ingest_sequence_preserved": watermark,
        "raw_event_count_unchanged": store.count(),
        "semantics": "only old terminal projection entries compacted; raw event history unchanged",
    }, indent=2))


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


@app.command()
def prioritize(
    limit: int = typer.Option(50, min=1, max=1000, help="Maximum ranked state records."),
    db: Path = typer.Option(database_path(), "--db", help="SQLite event store."),
) -> None:
    """Rank observed state by transparent recency and operational-salience heuristics."""
    from aie.relevance import rank_environment_state
    from aie.state_model import EnvironmentProjection

    try:
        saved = EventStore(db).load_state_snapshot("aie.environment.v1")
    except ValueError as exc:
        console.print(f"[red]Saved projection integrity check failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    if saved is None:
        console.print("No saved projection. Run aie state first.")
        raise typer.Exit(2)
    version, _, payload = saved
    if version != 1:
        console.print("[red]Unsupported environment snapshot version.[/red]")
        raise typer.Exit(2)
    try:
        projection = EnvironmentProjection.from_dict(json.loads(payload))
        ranked = rank_environment_state(projection, limit=limit)
    except (ValueError, TypeError, KeyError) as exc:
        console.print(f"[red]Saved projection is invalid:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps({
        "ranking_semantics": "retrieval_priority_not_truth_or_calibrated_confidence",
        "records": ranked,
    }, indent=2))


@app.command()
def think(
    question: str = typer.Argument(..., help="Question about the currently saved observed state."),
    task: str = typer.Option("routine", help="Local model policy: routine or complex."),
    timeout: float = typer.Option(90.0, min=1.0, max=300.0),
    include_memory: bool = typer.Option(False, "--include-memory", help="Include matching non-sensitive user-created memories."),
    include_goals: bool = typer.Option(False, "--include-goals", help="Include active and paused user-authored goals."),
    db: Path = typer.Option(database_path(), "--db", help="SQLite event store."),
) -> None:
    """Analyze saved observations with a local model; this command cannot execute actions."""
    from aie.cognition import build_cognitive_messages
    from aie.context import build_environment_context
    from aie.ollama import OllamaClient, OllamaError
    from aie.state_model import EnvironmentProjection

    if task not in {"routine", "complex"}:
        raise typer.BadParameter("task must be routine or complex")
    try:
        saved = EventStore(db).load_state_snapshot("aie.environment.v1")
    except ValueError as exc:
        console.print(f"[red]Saved projection integrity check failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    if saved is None:
        console.print("No saved projection. Run aie state first.")
        raise typer.Exit(2)
    version, _, payload = saved
    if version != 1:
        console.print("[red]Unsupported environment snapshot version.[/red]")
        raise typer.Exit(2)
    try:
        projection = EnvironmentProjection.from_dict(json.loads(payload))
        packet = build_environment_context(
            projection, max_processes=12, max_entities=12
        )
        for collection in ("processes", "entities"):
            for item in packet[collection]:
                refs = item.get("evidence_ids", [])
                if len(refs) > 8:
                    item["evidence_truncated"] = True
                item["evidence_ids"] = refs[-8:]
        if include_memory:
            from aie.memory import MemoryStore
            matches = MemoryStore(db).search(
                question[:1000], include_sensitive=False, limit=5
            )
            packet["retrieved_memories"] = [{
                "memory_id": item["memory_id"],
                "kind": item["kind"],
                "content": item["content"][:1000],
                "provenance_ids": item["provenance_ids"][-8:],
                "confidence": item["confidence"],
                "verification": item["verification"],
                "sensitivity": item["sensitivity"],
                "tags": item["tags"][:8],
                "created_at": item["created_at"],
                "expires_at": item["expires_at"],
            } for item in matches]
        if include_goals:
            from aie.goals import GoalStore
            goal_store = GoalStore(db)
            goals = goal_store.list(status="active", limit=6) + goal_store.list(status="paused", limit=6)
            goals.sort(key=lambda goal: (goal["updated_at"], goal["goal_id"]), reverse=True)
            packet["user_goals"] = [{
                "goal_id": goal["goal_id"],
                "title": goal["title"][:160],
                "description": goal["description"][:400],
                "status": goal["status"],
                "progress": goal["progress"],
                "steps": [{
                    "step_id": step["step_id"],
                    "title": step["title"][:160],
                    "status": step["status"],
                    "ready": step["ready"],
                    "dependencies": step["dependencies"][:8],
                } for step in goal["steps"][:10]],
            } for goal in goals[:6]]
        messages = build_cognitive_messages(packet, question)
    except (ValueError, TypeError, KeyError) as exc:
        console.print(f"[red]Could not prepare bounded context:[/red] {exc}")
        raise typer.Exit(2) from exc

    installed = discover_local_models()
    memory = runtime_profile()["memory_available_gib"]
    decision = choose_local_model(task, installed, memory)
    if not decision.available or decision.selected_model is None:
        console.print(f"[yellow]No eligible local model:[/yellow] {decision.reason}")
        raise typer.Exit(2)
    try:
        result = OllamaClient(timeout=timeout).chat(
            decision.selected_model,
            messages,
            options={"num_predict": 512, "temperature": 0.2},
        )
    except (OllamaError, ValueError) as exc:
        console.print(f"[red]Local analysis failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(result.content)
    console.print(
        "[dim]Local analysis only. Output is model-generated and does not alter system state.[/dim]"
    )


@app.command("memory-add")
def memory_add(
    content: str = typer.Argument(..., help="Explicit memory text; never generated automatically."),
    kind: str = typer.Option("episodic", help="working, episodic, semantic, procedural or prospective."),
    confidence: float = typer.Option(0.5, min=0.0, max=1.0),
    sensitivity: str = typer.Option("internal", help="public, internal or sensitive."),
    verification: str = typer.Option("unverified", help="unverified, supported, disputed or verified."),
    tags: str = typer.Option("", help="Comma-separated tags."),
    provenance: str = typer.Option("", help="Comma-separated source/event IDs."),
    ttl_days: int | None = typer.Option(None, min=1, max=36500),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Add a user-supplied memory record with explicit provenance and retention metadata."""
    from aie.memory import MemoryStore

    try:
        record = MemoryStore(db).add(
            content, kind=kind, confidence=confidence, sensitivity=sensitivity,
            verification=verification,
            tags=[item.strip() for item in tags.split(",") if item.strip()],
            provenance_ids=[item.strip() for item in provenance.split(",") if item.strip()],
            ttl_days=ttl_days,
        )
    except ValueError as exc:
        console.print(f"[red]Memory was not saved:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps({
        "memory_id": record["memory_id"], "kind": record["kind"],
        "sensitivity": record["sensitivity"], "verification": record["verification"],
        "expires_at": record["expires_at"],
    }))


@app.command("memory-search")
def memory_search(
    query: str = typer.Argument(""),
    kind: str | None = typer.Option(None),
    include_sensitive: bool = typer.Option(False, "--include-sensitive"),
    limit: int = typer.Option(20, min=1, max=100),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Search unexpired local memories; sensitive records are excluded by default."""
    from aie.memory import MemoryStore

    try:
        records = MemoryStore(db).search(
            query, kind=kind, include_sensitive=include_sensitive, limit=limit
        )
    except ValueError as exc:
        console.print(f"[red]Memory search failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(records, indent=2))


@app.command("memory-delete")
def memory_delete(
    memory_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Explicitly delete one memory record by ID."""
    from aie.memory import MemoryStore

    try:
        deleted = MemoryStore(db).delete(memory_id)
    except ValueError as exc:
        console.print(f"[red]Memory deletion failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print("Deleted." if deleted else "No matching memory record.")


@app.command("memory-prune")
def memory_prune(
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Explicitly remove expired memory records."""
    from aie.memory import MemoryStore

    deleted = MemoryStore(db).prune_expired()
    console.print(f"Expired memory records deleted: {deleted}")


@app.command("memory-correct")
def memory_correct(
    memory_id: str = typer.Argument(...),
    content: str | None = typer.Option(None, help="Replacement content."),
    confidence: float | None = typer.Option(None, min=0.0, max=1.0),
    verification: str | None = typer.Option(None),
    tags: str | None = typer.Option(None, help="Replacement comma-separated tags."),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Explicitly correct a memory while preserving its provenance and identity."""
    from aie.memory import MemoryStore

    try:
        changed = MemoryStore(db).revise(
            memory_id, content=content, confidence=confidence,
            verification=verification,
            tags=None if tags is None else [item.strip() for item in tags.split(",") if item.strip()],
        )
    except ValueError as exc:
        console.print(f"[red]Memory correction failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print("Updated." if changed else "No matching memory record.")


@app.command("memory-export")
def memory_export(
    output: Path = typer.Argument(...),
    include_sensitive: bool = typer.Option(False, "--include-sensitive"),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Export unexpired memories to a new JSONL file; sensitive export is opt-in."""
    from aie.memory import MemoryStore

    try:
        count = MemoryStore(db).export_jsonl(output, include_sensitive=include_sensitive)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Memory export failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Exported {count} memory records to {output}")


@app.command("memory-history")
def memory_history(
    memory_id: str = typer.Argument(...),
    limit: int = typer.Option(20, min=1, max=100),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Review previous versions of a corrected memory record."""
    from aie.memory import MemoryStore

    try:
        revisions = MemoryStore(db).history(memory_id, limit=limit)
    except ValueError as exc:
        console.print(f"[red]Memory history failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(revisions, indent=2))


@app.command("goal-add")
def goal_add(
    title: str = typer.Argument(...),
    description: str = typer.Option("", help="Goal context and success criteria."),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Create a persistent user-directed goal; no steps are executed automatically."""
    from aie.goals import GoalStore

    try:
        goal = GoalStore(db).create(title, description)
    except ValueError as exc:
        console.print(f"[red]Goal creation failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(goal, indent=2))


@app.command("goal-list")
def goal_list(
    status: str | None = typer.Option(None),
    limit: int = typer.Option(50, min=1, max=200),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """List persistent goals and their progress."""
    from aie.goals import GoalStore

    try:
        goals = GoalStore(db).list(status=status, limit=limit)
    except ValueError as exc:
        console.print(f"[red]Goal listing failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(goals, indent=2))


@app.command("goal-show")
def goal_show(
    goal_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Show one goal, dependency readiness and progress."""
    from aie.goals import GoalStore

    try:
        goal = GoalStore(db).get(goal_id)
    except ValueError as exc:
        console.print(f"[red]Goal lookup failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    if goal is None:
        console.print("[yellow]Goal not found.[/yellow]")
        raise typer.Exit(2)
    console.print_json(json.dumps(goal, indent=2))


@app.command("goal-step-add")
def goal_step_add(
    goal_id: str = typer.Argument(...),
    title: str = typer.Argument(...),
    description: str = typer.Option("", help="Step completion criteria."),
    depends_on: str = typer.Option("", help="Comma-separated prerequisite step IDs."),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Add a manually specified step and optional prerequisites to an active goal."""
    from aie.goals import GoalStore

    try:
        dependencies = [item.strip() for item in depends_on.split(",") if item.strip()]
        step = GoalStore(db).add_step(goal_id, title, description, dependencies)
    except ValueError as exc:
        console.print(f"[red]Step creation failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(step, indent=2))


@app.command("goal-step-update")
def goal_step_update(
    goal_id: str = typer.Argument(...),
    step_id: str = typer.Argument(...),
    status: str = typer.Argument(..., help="pending, in_progress, blocked, completed or cancelled."),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Update one step; dependency gates are enforced by the goal state machine."""
    from aie.goals import GoalStore

    try:
        step = GoalStore(db).update_step(goal_id, step_id, status)
    except ValueError as exc:
        console.print(f"[red]Step update rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(step, indent=2))


@app.command("goal-status")
def goal_status(
    goal_id: str = typer.Argument(...),
    status: str = typer.Argument(..., help="active, paused, completed or abandoned."),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Pause, resume or explicitly close a goal."""
    from aie.goals import GoalStore

    try:
        goal = GoalStore(db).set_goal_status(goal_id, status)
    except ValueError as exc:
        console.print(f"[red]Goal transition rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(goal, indent=2))


@app.command("goal-history")
def goal_history(
    goal_id: str = typer.Argument(...),
    limit: int = typer.Option(100, min=1, max=500),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Review append-only goal and step transition history."""
    from aie.goals import GoalStore

    try:
        history = GoalStore(db).history(goal_id, limit)
    except ValueError as exc:
        console.print(f"[red]Goal history failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(history, indent=2))


@app.command("goal-suggest")
def goal_suggest(goal_id: str = typer.Argument(...), db: Path = typer.Option(database_path(), "--db")) -> None:
    """Generate and persist a local plan draft for explicit human review."""
    from aie.goals import GoalStore
    from aie.planning import build_plan_messages, plan_schema, validate_plan_output
    from aie.ollama import OllamaClient, OllamaError

    store = GoalStore(db)
    try:
        goal = store.get(goal_id)
        if goal is None or goal["status"] not in {"active", "paused"}:
            raise ValueError("an active or paused goal is required")
        messages = build_plan_messages(goal)
        installed = discover_local_models()
        decision = choose_local_model("routine", installed, runtime_profile()["memory_available_gib"])
        if not decision.available or decision.selected_model is None:
            raise ValueError(decision.reason)
        result = OllamaClient(timeout=90).chat(
            decision.selected_model, messages, format=plan_schema(),
            options={"num_predict": 1024, "temperature": 0.1},
        )
        plan = validate_plan_output(result.content)
        draft = store.create_plan_draft(goal_id, plan, result.model)
    except (OllamaError, ValueError, TypeError, KeyError) as exc:
        console.print(f"[red]Plan suggestion rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(draft, indent=2))
    console.print("[dim]Saved as pending review. No goal steps were changed or executed.[/dim]")


@app.command("goal-draft-list")
def goal_draft_list(
    goal_id: str = typer.Argument(...),
    status: str | None = typer.Option(None, help="pending_review, accepted or rejected."),
    limit: int = typer.Option(20, min=1, max=100),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """List persisted plan drafts for one goal."""
    from aie.goals import GoalStore
    try:
        drafts = GoalStore(db).list_plan_drafts(goal_id, status, limit)
    except ValueError as exc:
        console.print(f"[red]Draft listing failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(drafts, indent=2))


@app.command("goal-draft-show")
def goal_draft_show(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Show one saved plan draft after integrity verification."""
    from aie.goals import GoalStore
    try:
        draft = GoalStore(db).get_plan_draft(draft_id)
    except ValueError as exc:
        console.print(f"[red]Draft verification failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    if draft is None:
        console.print("[yellow]Draft not found.[/yellow]")
        raise typer.Exit(2)
    console.print_json(json.dumps(draft, indent=2))


@app.command("goal-draft-accept")
def goal_draft_accept(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Explicitly accept a reviewed draft and add its steps; nothing is executed."""
    from aie.goals import GoalStore
    try:
        result = GoalStore(db).resolve_plan_draft(draft_id, "accepted")
    except ValueError as exc:
        console.print(f"[red]Draft acceptance rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(result, indent=2))
    console.print("[dim]Steps added to the goal only; no commands or OS actions were run.[/dim]")


@app.command("goal-draft-reject")
def goal_draft_reject(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Explicitly reject a pending plan draft."""
    from aie.goals import GoalStore
    try:
        result = GoalStore(db).resolve_plan_draft(draft_id, "rejected")
    except ValueError as exc:
        console.print(f"[red]Draft rejection failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(result, indent=2))


@app.command("settings-search")
def settings_search(
    query: str = typer.Argument("", help="Search URI, title, category or description."),
    limit: int = typer.Option(50, min=1, max=500),
    catalog: Path | None = typer.Option(None, "--catalog", help="Optional imported JSON/CSV catalogue."),
) -> None:
    """Search the local ms-settings URI catalogue; does not open or change Settings."""
    from aie.ms_settings import documented_catalog, load_catalog, search_catalog

    try:
        entries = load_catalog(catalog) if catalog else documented_catalog()
        matches = search_catalog(entries, query, limit)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        console.print(f"[red]Settings catalogue error:[/red] {exc}")
        raise typer.Exit(2) from exc
    table = Table("URI", "Destination", "Category", "Validation")
    for item in matches:
        table.add_row(item.uri, item.title, item.category, item.validation_status)
    console.print(table)
    console.print(f"Matches: {len(matches)} | Catalogue entries: {len(entries)}")


@app.command("settings-import")
def settings_import(
    source: Path = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Option(Path("settings-catalog.json"), "--output", "-o"),
    merge: bool = typer.Option(True, "--merge/--replace", help="Merge with existing output catalogue when present."),
) -> None:
    """Validate and import a local JSON/CSV ms-settings catalogue; never executes URIs."""
    from aie.ms_settings import documented_catalog, load_catalog, merge_catalog, save_catalog

    try:
        incoming = load_catalog(source)
        existing = load_catalog(output) if merge and output.exists() else documented_catalog() if merge else []
        combined = merge_catalog(existing, incoming)
        save_catalog(output, combined)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        console.print(f"[red]Settings catalogue import failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Imported {len(incoming)} unique entries; catalogue now contains {len(combined)} entries at {output}")




@app.command("experience-add")
def experience_add(
    task_key: str = typer.Argument(..., help="Stable task family key, e.g. settings.open_display."),
    summary: str = typer.Argument(..., help="Concise outcome summary."),
    outcome: str = typer.Argument(..., help="success, partial, failure or unknown."),
    evidence: str = typer.Option("", "--evidence", help="Comma-separated event/evidence IDs."),
    verifier: str = typer.Option("user", help="user, system or reviewed-evidence."),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Record an observed task outcome for later evidence-gated learning."""
    from aie.learning import ExperienceStore
    try:
        record = ExperienceStore(db).record(
            task_key, summary, outcome,
            evidence_ids=[part.strip() for part in evidence.split(",") if part.strip()],
            verifier=verifier,
        )
    except ValueError as exc:
        console.print(f"[red]Experience rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(record, indent=2))


@app.command("experience-list")
def experience_list(
    task_key: str = typer.Argument(...),
    limit: int = typer.Option(50, min=1, max=200),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Review recorded outcomes for one task family."""
    from aie.learning import ExperienceStore
    try:
        records = ExperienceStore(db).list_experiences(task_key, limit)
    except ValueError as exc:
        console.print(f"[red]Experience query failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(records, indent=2))


@app.command("learn-report")
def learn_report(
    task_key: str = typer.Argument(..., help="Task family key to evaluate."),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """Report descriptive task outcomes, evidence coverage and uncertainty."""
    from aie.learning import ExperienceStore
    try:
        report = ExperienceStore(db).task_report(task_key)
    except ValueError as exc:
        console.print(f"[red]Learning report failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(report, indent=2))


@app.command("skill-draft-list")
def skill_draft_list(
    task_key: str | None = typer.Argument(None, help="Optional task family filter."),
    status: str | None = typer.Option(None, help="pending_review, accepted or rejected."),
    limit: int = typer.Option(50, min=1, max=200),
    db: Path = typer.Option(database_path(), "--db", help="Local SQLite database."),
) -> None:
    """List skill drafts after verifying each stored payload digest."""
    from aie.learning import ExperienceStore
    try:
        drafts = ExperienceStore(db).list_skill_drafts(task_key, status, limit)
    except ValueError as exc:
        console.print(f"[red]Skill draft listing failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(drafts, indent=2))


@app.command("experience-relationships")
def experience_relationships(
    task_key: str = typer.Argument(...),
    limit: int = typer.Option(200, min=1, max=1000),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Inspect preserved duplicate and contradictory experience links."""
    from aie.learning import ExperienceStore
    try:
        report = ExperienceStore(db).task_relationships(task_key, limit)
    except ValueError as exc:
        console.print(f"[red]Relationship query failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(report, indent=2))


@app.command("knowledge-consolidate")
def knowledge_consolidate(
    task_key: str = typer.Argument(...),
    minimum_repetitions: int = typer.Option(3, min=2, max=50),
    limit: int = typer.Option(20, min=1, max=100),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Create review-only knowledge candidates from repeated, non-contradictory experiences."""
    from aie.learning import ExperienceStore
    try:
        drafts = ExperienceStore(db).create_knowledge_drafts(
            task_key, minimum_repetitions=minimum_repetitions, limit=limit
        )
    except ValueError as exc:
        console.print(f"[red]Knowledge consolidation failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(drafts, indent=2))


@app.command("knowledge-draft-list")
def knowledge_draft_list(
    task_key: str | None = typer.Argument(None),
    status: str | None = typer.Option(None),
    limit: int = typer.Option(50, min=1, max=200),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """List integrity-checked knowledge candidates."""
    from aie.learning import ExperienceStore
    try:
        drafts = ExperienceStore(db).list_knowledge_drafts(task_key, status, limit)
    except ValueError as exc:
        console.print(f"[red]Knowledge draft listing failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(drafts, indent=2))


@app.command("knowledge-draft-review")
def knowledge_draft_review(
    knowledge_id: str = typer.Argument(...),
    decision: str = typer.Argument(..., help="accepted or rejected"),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Accept or reject one knowledge candidate; review is one-time and audited."""
    from aie.learning import ExperienceStore
    try:
        draft = ExperienceStore(db).resolve_knowledge_draft(knowledge_id, decision)
    except ValueError as exc:
        console.print(f"[red]Knowledge review rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(draft, indent=2))


@app.command("knowledge-publish")
def knowledge_publish(
    knowledge_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db", help="Learning database."),
    memory_db: Path = typer.Option(database_path(), "--memory-db", help="Memory database.")
) -> None:
    """Publish an accepted, evidence-backed success candidate into semantic memory."""
    from aie.learning import ExperienceStore
    from aie.memory import MemoryStore
    try:
        draft = ExperienceStore(db).get_knowledge_draft(knowledge_id)
        if draft is None or draft["status"] != "accepted":
            raise ValueError("knowledge candidate must be accepted before publication")
        if draft["outcome"] != "success" or not draft["evidence_ids"]:
            raise ValueError("only repeated successful knowledge with evidence can enter semantic memory")
        record = MemoryStore(memory_db).import_reviewed_knowledge(
            knowledge_id, draft["content"],
            provenance_ids=list(dict.fromkeys(draft["provenance_ids"] + draft["evidence_ids"])),
            tags=["task:" + draft["task_key"], "outcome:success"],
            confidence=0.7,
        )
    except ValueError as exc:
        console.print(f"[red]Knowledge publication rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps({
        "knowledge_id": knowledge_id, "memory_id": record["memory_id"],
        "kind": record["kind"], "verification": record["verification"],
        "idempotent": True, "provenance_count": len(record["provenance_ids"]),
    }, indent=2))


@app.command("skill-publish")
def skill_publish(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Freeze an accepted draft as an immutable numbered skill version."""
    from aie.learning import ExperienceStore
    try:
        version = ExperienceStore(db).publish_skill_draft(draft_id)
    except ValueError as exc:
        console.print(f"[red]Skill publication rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(version, indent=2))
    console.print("[dim]Versioned reference only. It is not executable or automation-eligible.[/dim]")


@app.command("skill-version-list")
def skill_version_list(
    task_key: str | None = typer.Argument(None),
    title: str | None = typer.Option(None, help="Optional case-insensitive skill title."),
    limit: int = typer.Option(100, min=1, max=500),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """List immutable skill versions after digest verification."""
    from aie.learning import ExperienceStore
    try:
        versions = ExperienceStore(db).list_skill_versions(task_key, title, limit)
    except ValueError as exc:
        console.print(f"[red]Skill version query failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(versions, indent=2))


@app.command("skill-evaluate")
def skill_evaluate(
    skill_id: str = typer.Argument(...),
    version: int = typer.Argument(..., min=1),
    suite_key: str = typer.Argument(...),
    trials: int = typer.Option(..., min=1, max=10000),
    successes: int = typer.Option(..., min=0),
    partials: int = typer.Option(..., min=0),
    failures: int = typer.Option(..., min=0),
    unknown: int = typer.Option(0, min=0),
    evidence: str = typer.Option(..., help="Comma-separated evaluation evidence references."),
    evaluator: str = typer.Option("reviewed-evidence", help="user or reviewed-evidence"),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Record held-out skill-suite outcomes and compare against an earlier version."""
    from aie.learning import ExperienceStore
    try:
        report = ExperienceStore(db).record_skill_evaluation(
            skill_id, version, suite_key, trials=trials, successes=successes,
            partials=partials, failures=failures, unknown=unknown,
            evidence_ids=[item.strip() for item in evidence.split(",") if item.strip()],
            evaluator=evaluator,
        )
    except ValueError as exc:
        console.print(f"[red]Skill evaluation rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(report, indent=2))


@app.command("skill-evaluation-list")
def skill_evaluation_list(
    skill_id: str = typer.Argument(...),
    version: int | None = typer.Option(None, min=1),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Review recorded evaluation results for a skill and its versions."""
    from aie.learning import ExperienceStore
    try:
        reports = ExperienceStore(db).list_skill_evaluations(skill_id, version)
    except ValueError as exc:
        console.print(f"[red]Skill evaluation query failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(reports, indent=2))


@app.command("skill-draft")
def skill_draft(
    task_key: str = typer.Argument(...),
    title: str = typer.Argument(...),
    steps_json: str = typer.Argument(..., help="JSON array of proposed human-readable steps."),
    minimum_successes: int = typer.Option(3, min=2, max=20),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Create a reusable procedural-skill draft after repeated evidence-backed success."""
    from aie.learning import ExperienceStore
    try:
        steps = json.loads(steps_json)
        draft = ExperienceStore(db).create_skill_draft(
            task_key, title, steps, minimum_successes=minimum_successes
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        console.print(f"[red]Skill draft rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(draft, indent=2))
    console.print("[dim]Pending review only. This skill is not executable and cannot change policy.[/dim]")


@app.command("skill-draft-show")
def skill_draft_show(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Show a skill draft after integrity verification."""
    from aie.learning import ExperienceStore
    try:
        draft = ExperienceStore(db).get_skill_draft(draft_id)
    except ValueError as exc:
        console.print(f"[red]Skill draft verification failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    if draft is None:
        console.print("[yellow]Skill draft not found.[/yellow]")
        raise typer.Exit(2)
    console.print_json(json.dumps(draft, indent=2))


@app.command("skill-draft-accept")
def skill_draft_accept(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Accept a reviewed skill record; does not grant execution or OS capabilities."""
    from aie.learning import ExperienceStore
    try:
        draft = ExperienceStore(db).resolve_skill_draft(draft_id, "accepted")
    except ValueError as exc:
        console.print(f"[red]Skill acceptance rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(draft, indent=2))
    console.print("[dim]Stored as a reviewed procedural reference only; nothing was executed.[/dim]")


@app.command("skill-draft-reject")
def skill_draft_reject(
    draft_id: str = typer.Argument(...),
    db: Path = typer.Option(database_path(), "--db"),
) -> None:
    """Reject a pending procedural-skill draft."""
    from aie.learning import ExperienceStore
    try:
        draft = ExperienceStore(db).resolve_skill_draft(draft_id, "rejected")
    except ValueError as exc:
        console.print(f"[red]Skill rejection failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(draft, indent=2))


if __name__ == "__main__":
    app()
