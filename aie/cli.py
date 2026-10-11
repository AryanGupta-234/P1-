"""AIE command-line interface."""
from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timedelta, timezone
from typing import Literal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aie import __version__
from aie.config import (
    capability_manifest_dir,
    database_path,
    memory_database_path,
    observer_is_paused,
    policy_audit_database_path,
    set_observer_paused,
)
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



def _print_video_diagnostic(event) -> None:
    """Present a new diagnostic suggestion without executing its recommendation."""
    severity = str(event.data.get("severity", "medium")).upper()
    cause = str(event.data.get("cause", event.entity.name))
    confidence = float(event.data.get("confidence", 0.0))
    recommendation = str(event.data.get("recommendation", "Review diagnostic evidence."))
    color = "red" if severity == "HIGH" else "yellow"
    console.print(
        f"\n[{color}]P1 video intelligence: {cause} ({severity}, {confidence:.0%})[/{color}]"
    )
    console.print(recommendation)
    console.print("[dim]Suggestion only — no action was executed.[/dim]")


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
    ui_tree: bool = typer.Option(False, "--ui-tree/--no-ui-tree", help="Opt in to structural UI Automation metadata."),
    ui_tree_apps: str | None = typer.Option(None, help="Comma-separated process allowlist, e.g. msedge.exe,notepad.exe."),
    ui_tree_sample_interval: float = typer.Option(10.0, min=2.0, max=300.0),
    event_logs: bool = typer.Option(False, "--event-logs/--no-event-logs", help="Opt in to Application/System event metadata."),
    event_log_channels: str = typer.Option("Application,System", help="Comma-separated allowlisted Windows event log channels."),
    event_log_interval: float = typer.Option(30.0, min=5.0, max=300.0),
    event_log_max_records: int = typer.Option(50, min=1, max=200),
    process_resources: bool = typer.Option(False, "--process-resources/--no-process-resources", help="Opt in to bounded systemwide process resource snapshots."),
    process_resource_interval: float = typer.Option(10.0, min=2.0, max=300.0),
    process_resource_max_processes: int = typer.Option(256, min=1, max=512),
    etw: bool = typer.Option(False, "--etw/--no-etw", help="Opt in to kernel ETW process lifecycle telemetry (elevated token required)."),
    etw_max_events_per_poll: int = typer.Option(100, min=1, max=1000),
) -> None:
    """Observe selected Windows metadata (read-only)."""
    from aie.runtime import observe as run_observer

    allowed_ui_apps = {
        item.strip().casefold()
        for item in (ui_tree_apps or "").split(",")
        if item.strip()
    }
    if ui_tree and not allowed_ui_apps:
        console.print("[red]UI Automation requires --ui-tree-apps with an explicit app allowlist.[/red]")
        raise typer.Exit(2)
    if etw:
        import importlib.util

        if importlib.util.find_spec("pyetwkit") is None:
            console.print(
                "[red]Install ETW support with: python -m pip install -e .[windows][/red]"
            )
            raise typer.Exit(2)

    selected_event_logs = tuple(
        item.strip() for item in event_log_channels.split(",") if item.strip()
    )
    if event_logs:
        invalid_channels = set(selected_event_logs) - {"Application", "System"}
        if not selected_event_logs or invalid_channels:
            console.print("[red]Event log channels must be Application and/or System.[/red]")
            raise typer.Exit(2)
        try:
            import win32evtlog  # noqa: F401
        except ImportError:
            console.print("[red]Install Windows event log support with: python -m pip install -e .[windows][/red]")
            raise typer.Exit(2)

    if ui_tree:
        import importlib.util
        if importlib.util.find_spec("pywinauto") is None:
            console.print("[red]Install UI Automation support with: python -m pip install -e .[windows][/red]")
            raise typer.Exit(2)

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
            on_diagnostic=_print_video_diagnostic,
            include_ui_tree=ui_tree,
            ui_tree_app_names=allowed_ui_apps,
            ui_tree_sample_interval=ui_tree_sample_interval,
            include_event_logs=event_logs,
            event_log_channels=selected_event_logs,
            event_log_interval=event_log_interval,
            event_log_max_records=event_log_max_records,
            include_process_resources=process_resources,
            process_resource_interval=process_resource_interval,
            process_resource_max_processes=process_resource_max_processes,
            include_etw=etw,
            etw_max_events_per_poll=etw_max_events_per_poll,
        )
    except (OSError, RuntimeError, ValueError) as exc:
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



@app.command("activity")
def show_activity(
    hours: float = typer.Option(4.0, min=0.1, max=168.0, help="Look back this many hours."),
    session_gap_minutes: float = typer.Option(5.0, min=0.5, max=60.0),
    limit: int = typer.Option(1000, min=1, max=5000),
    include_sensitive: bool = typer.Option(False, help="Include sensitive event metadata (payload text is never shown)."),
) -> None:
    """Show a privacy-safe timeline grouped into temporal activity sessions."""
    from aie.context.activity import build_activity_timeline

    now = datetime.now(timezone.utc)
    store = EventStore(database_path())
    events = store.query_events(
        since=now - timedelta(hours=hours),
        limit=limit,
    )
    timeline = build_activity_timeline(
        events,
        now=now,
        max_age_seconds=hours * 3600,
        session_gap_seconds=session_gap_minutes * 60,
        include_sensitive=include_sensitive,
    )
    if not timeline.sessions:
        console.print("No activity events in the selected time window.")
        return

    console.print(
        f"Activity timeline · {timeline.event_count} events · "
        f"{len(timeline.sessions)} sessions · lookback {hours:g}h"
    )
    for session in timeline.sessions:
        duration = max(0.0, (session.ended_at - session.started_at).total_seconds())
        state = "CURRENT" if session.session_id == timeline.current_session_id else "SESSION"
        heading = (
            f"{state} · {session.started_at.astimezone().strftime('%H:%M:%S')}–"
            f"{session.ended_at.astimezone().strftime('%H:%M:%S')} · "
            f"{duration / 60:.1f} min · {session.event_count} events"
        )
        console.print(f"\n[bold]{heading}[/bold]")
        if session.applications:
            console.print("Apps: " + ", ".join(session.applications))
        console.print("Signals: " + ", ".join(session.kinds))
        table = Table("Time", "Kind", "Observation", "Confidence")
        for signal in session.signals[-20:]:
            table.add_row(
                signal.timestamp.astimezone().strftime("%H:%M:%S"),
                signal.kind,
                signal.title,
                f"{signal.confidence:.0%}",
            )
        console.print(table)
    console.print(
        "[dim]Sessions are time-based groupings, not inferred user intent. "
        "Raw event payloads, window titles, UIA text and feedback notes are not displayed.[/dim]"
    )


@app.command("context")
def show_context(
    max_age_seconds: float = typer.Option(30.0, min=1.0, max=300.0),
) -> None:
    """Show the latest correlated video, foreground-app and network context."""
    from aie.context.video import build_video_observation_context
    from aie.diagnostics.video_buffering import diagnose_video_buffering

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

    diagnosis = diagnose_video_buffering(context.metrics)
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
    if diagnosis.status == "findings":
        diagnostic_table = Table("Hypothesis", "Severity", "Confidence", "Evidence")
        for finding in diagnosis.findings:
            diagnostic_table.add_row(
                finding.cause,
                finding.severity,
                f"{finding.confidence:.0%}",
                "; ".join(finding.evidence),
            )
        console.print("\n[bold]Diagnostic hypotheses[/bold]")
        console.print(diagnostic_table)
    else:
        console.print(
            "No root-cause hypothesis met the current evidence thresholds. "
            "Keep collecting signals; unknown measurements remain unknown."
        )
    console.print(
        f"Evidence records: {len(context.evidence_event_ids)} · "
        f"Context age: {(context.generated_at - context.observed_at).total_seconds():.1f}s"
    )


@app.command()
def pause() -> None:
    """Pause all running AIE observer instances for this Windows user."""
    set_observer_paused(True)
    console.print("[yellow]AIE observation paused.[/yellow] Stored events were not deleted.")


@app.command()
def resume() -> None:
    """Resume AIE observer instances after a global pause."""
    set_observer_paused(False)
    console.print("[green]AIE observation resumed.[/green]")


@app.command()
def status() -> None:
    """Show observer control state and local event-store size."""
    paused = observer_is_paused()
    store = EventStore(database_path())
    table = Table("Component", "State")
    table.add_row("Observer", "[yellow]PAUSED[/yellow]" if paused else "[green]RUNNABLE[/green]")
    table.add_row("Stored events", str(store.count()))
    latest = store.recent(1)
    table.add_row(
        "Latest observation",
        latest[0].timestamp.isoformat() if latest else "No events stored",
    )
    console.print(table)


@app.command()
def prune(
    older_than_days: int = typer.Option(30, min=1, max=3650, help="Delete records older than this many days."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm deletion of old local event records."),
) -> None:
    """Preview or delete old local observation events (never deletes recent events)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    store = EventStore(database_path())
    candidates = store.count_before(cutoff)
    if not confirm:
        console.print(
            f"{candidates} event(s) are older than {older_than_days} days. "
            "No data was deleted. Re-run with --confirm to prune them."
        )
        return
    deleted = store.delete_before(cutoff)
    console.print(f"Deleted {deleted} event(s) older than {older_than_days} days.")


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Prompt to send to the model."),
    task: Literal["routine", "complex"] = typer.Option("routine", help="Choose the reasoning tier."),
    provider: Literal["local", "cloud"] = typer.Option("local", help="Select local Ollama or explicitly enabled cloud inference."),
    allow_remote_ollama: bool = typer.Option(
        False,
        "--allow-remote-ollama",
        help="Explicitly permit AIE_OLLAMA_URL to point to a remote HTTPS Ollama host.",
    ),
    allow_cloud_egress: bool = typer.Option(
        False,
        "--allow-cloud-egress",
        help="Explicitly authorize sending this prompt to the configured HTTPS cloud provider.",
    ),
    with_activity: bool = typer.Option(
        False,
        "--with-activity/--no-activity",
        help="Explicitly attach a bounded safe activity summary to this request.",
    ),
    activity_lookback_minutes: int = typer.Option(120, min=1, max=1440),
    confirm_activity_egress: bool = typer.Option(
        False,
        help="Confirm sending safe activity summaries to a remote model endpoint.",
    ),
    with_memory: bool = typer.Option(
        False,
        "--with-memory/--no-memory",
        help="Explicitly attach matching local memories to this request.",
    ),
    semantic_memory: bool = typer.Option(False, "--semantic-memory/--lexical-memory", help="Use local embeddings for memory retrieval."),
    embedding_model: str = typer.Option("nomic-embed-text:latest", help="Already-installed local embedding model."),
    include_sensitive_memory: bool = typer.Option(
        False,
        help="Include sensitive memories (local inference only).",
    ),
    confirm_memory_egress: bool = typer.Option(
        False,
        help="Confirm sending non-sensitive memory references to a remote model endpoint.",
    ),
    temperature: float = typer.Option(0.2, min=0.0, max=2.0),
    max_output_tokens: int = typer.Option(512, min=32, max=4096),
    memory_limit: int = typer.Option(5, min=1, max=10),
    with_session: bool = typer.Option(
        False,
        "--with-session/--no-session",
        help="Attach the explicit current working-session metadata.",
    ),
    confirm_session_egress: bool = typer.Option(
        False,
        help="Confirm sending the explicit session label to a remote model endpoint.",
    ),
) -> None:
    """Send a prompt to local Ollama or an explicitly authorized HTTPS cloud model."""
    from aie.models.base import ChatMessage, ModelRequest
    from aie.models.ollama import OllamaClient
    from aie.models.router import LocalModelRouter

    memory_ids: tuple[str, ...] = ()
    remote_selected = provider == "cloud" or allow_remote_ollama
    if with_activity and remote_selected and not confirm_activity_egress:
        console.print("[red]Attaching activity context to a remote model needs --confirm-activity-egress.[/red]")
        raise typer.Exit(2)
    if semantic_memory and not with_memory:
        console.print("[red]--semantic-memory requires --with-memory.[/red]")
        raise typer.Exit(2)
    if include_sensitive_memory and not with_memory:
        console.print("[red]--include-sensitive-memory requires --with-memory.[/red]")
        raise typer.Exit(2)
    if with_memory and remote_selected and not confirm_memory_egress:
        console.print(
            "[red]Attaching memory to a remote model needs --confirm-memory-egress.[/red]"
        )
        raise typer.Exit(2)
    if with_session and remote_selected and not confirm_session_egress:
        console.print(
            "[red]Attaching session context to a remote model needs "
            "--confirm-session-egress.[/red]"
        )
        raise typer.Exit(2)
    if with_memory and remote_selected and include_sensitive_memory:
        console.print("[red]Sensitive memories cannot be attached to remote model requests.[/red]")
        raise typer.Exit(2)

    try:
        messages = [ChatMessage(role="user", content=prompt)]
        activity_event_count = 0
        session_id = None
        if with_activity:
            from aie.context.activity_context import build_activity_prompt_context

            activity_context = build_activity_prompt_context(
                EventStore(database_path()),
                lookback_minutes=activity_lookback_minutes,
            )
            activity_event_count = len(activity_context.event_ids)
            if activity_context.content:
                messages.insert(0, ChatMessage(role="system", content=activity_context.content))
        if with_session:
            from aie.context.task_session.context import build_task_session_prompt_context
            from aie.context.task_session.store import TaskSessionStore

            session_context = build_task_session_prompt_context(
                TaskSessionStore(task_session_database_path())
            )
            session_id = session_context.session_id
            if session_context.content:
                messages.insert(
                    0,
                    ChatMessage(role="system", content=session_context.content),
                )
        if with_memory:
            from aie.memory.prompt_context import build_memory_prompt_context
            from aie.memory.store import MemoryStore

            embedding_client = None
            if semantic_memory:
                from aie.models.ollama import OllamaClient

                embedding_client = OllamaClient()
            memory_context = build_memory_prompt_context(
                prompt,
                MemoryStore(memory_database_path()),
                include_sensitive=include_sensitive_memory,
                limit=memory_limit,
                semantic_model=embedding_model if semantic_memory else None,
                embedding_provider=embedding_client,
            )
            memory_ids = memory_context.memory_ids
            if memory_context.content:
                messages.insert(0, ChatMessage(role="system", content=memory_context.content))
    except (RuntimeError, ValueError, OSError) as exc:
        console.print(f"[red]Context retrieval unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc

    try:
        request = ModelRequest(
            task=task,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if provider == "cloud":
            from aie.models.openai_compatible import OpenAICompatibleClient

            cloud_client = OpenAICompatibleClient(
                allow_cloud_egress=allow_cloud_egress,
            )
            response = cloud_client.chat(request)
        else:
            if allow_cloud_egress:
                raise ValueError(
                    "--allow-cloud-egress is only meaningful with --provider cloud."
                )
            client = OllamaClient(allow_remote=allow_remote_ollama)
            response = LocalModelRouter(client).generate(request)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Model request unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc

    console.print(response.content)
    memory_note = (
        f" · Memory references: {len(memory_ids)} (explicit opt-in)"
        if with_memory
        else ""
    )
    activity_note = (
        f" · Activity signals: {activity_event_count} (explicit opt-in)"
        if with_activity
        else ""
    )
    session_note = (
        f" · Session: {session_id} (explicit opt-in)"
        if with_session and session_id
        else ""
    )
    console.print(
        f"\n[dim]Model: {response.model} · "
        f"Elapsed: {response.elapsed_seconds:.2f}s · "
        f"Prompt tokens: {response.prompt_tokens or 'unknown'} · "
        f"Output tokens: {response.completion_tokens or 'unknown'}"
        f"{memory_note}{activity_note}[/dim]"
    )

@app.command("session-start")
def session_start(label: str = typer.Argument(...)) -> None:
    """Start a user-controlled working session; no intent is inferred."""
    from aie.context.task_session.store import TaskSessionStore

    try:
        session = TaskSessionStore(task_session_database_path()).start(label)
    except ValueError as exc:
        console.print(f"[red]Session not started:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(
        f"[green]Session started.[/green] {session.label} · {session.session_id}"
    )


@app.command("session-status")
def session_status() -> None:
    """Show the explicit current working session."""
    from aie.context.task_session.store import TaskSessionStore

    session = TaskSessionStore(task_session_database_path()).current()
    if session is None:
        console.print("No active task session.")
        return
    console.print(
        f"[bold]{session.label}[/bold]\n"
        f"Session ID: {session.session_id}\n"
        f"Started: {session.started_at.isoformat()}"
    )


@app.command("session-end")
def session_end() -> None:
    """End the explicit current working session."""
    from aie.context.task_session.store import TaskSessionStore

    session = TaskSessionStore(task_session_database_path()).end()
    if session is None:
        console.print("No active task session.")
        return
    console.print(
        f"[green]Session ended.[/green] {session.label} · {session.session_id}"
    )


@app.command("sessions")
def sessions(limit: int = typer.Option(25, min=1, max=100)) -> None:
    """List explicit task sessions."""
    from aie.context.task_session.store import TaskSessionStore

    items = TaskSessionStore(task_session_database_path()).list(limit=limit)
    if not items:
        console.print("No task sessions recorded.")
        return
    table = Table("Status", "Label", "Started", "Ended", "Session ID")
    for item in items:
        table.add_row(
            item.status,
            item.label,
            item.started_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            item.ended_at.astimezone().strftime("%Y-%m-%d %H:%M:%S") if item.ended_at else "-",
            item.session_id,
        )
    console.print(table)


@app.command("feedback")
def feedback(
    diagnostic_event_id: str = typer.Argument(..., help="Diagnostic event ID shown by aie events."),
    outcome: Literal["resolved", "not_resolved", "not_attempted"] = typer.Option(
        ...,
        help="What happened after you tried the recommendation.",
    ),
    note: str | None = typer.Option(
        None,
        help="Optional feedback note; stored locally as sensitive data.",
    ),
) -> None:
    """Record whether a diagnostic recommendation helped."""
    from aie.learning.feedback import FeedbackRequest, record_diagnostic_feedback

    if note is not None and len(note) > 1000:
        console.print("[red]Feedback note must be at most 1000 characters.[/red]")
        raise typer.Exit(2)

    try:
        event = record_diagnostic_feedback(
            EventStore(database_path()),
            FeedbackRequest(
                diagnostic_event_id=diagnostic_event_id,
                outcome=outcome,
                note=note,
            ),
        )
    except ValueError as exc:
        console.print(f"[red]Feedback not recorded:[/red] {exc}")
        raise typer.Exit(2) from exc

    console.print(
        f"[green]Feedback saved locally.[/green] "
        f"Outcome: {event.data['outcome']} · Linked finding: {event.data['target_event_id']}"
    )



@app.command("screen")
def inspect_screen(
    max_age_seconds: float = typer.Option(30.0, min=1.0, max=300.0),
    limit: int = typer.Option(50, min=1, max=200),
) -> None:
    """Inspect the latest allowlisted UI Automation structure (never control text)."""
    store = EventStore(database_path())
    now = datetime.now(timezone.utc)
    snapshot = next(
        (
            event for event in store.recent(1000)
            if event.event_type == "window.uia_tree_snapshot"
            and event.timestamp.tzinfo is not None
            and 0 <= (now - event.timestamp).total_seconds() <= max_age_seconds
        ),
        None,
    )
    if snapshot is None:
        console.print(
            "No fresh UI Automation snapshot. UIA is off by default; run "
            "aie observe --ui-tree --ui-tree-apps <app.exe> for an allowlisted app."
        )
        return

    console.print(
        f"Structural snapshot: {snapshot.data.get('process_name', snapshot.entity.name)} · "
        f"{snapshot.data.get('node_count', 0)} controls · text collected: no"
    )
    table = Table("Index", "Parent", "Type", "Class", "Automation ID", "Bounds", "Enabled")
    nodes = snapshot.data.get("nodes", [])
    for node in nodes[:limit]:
        if not isinstance(node, dict):
            continue
        bounds = node.get("rectangle", [])
        bounds_text = ", ".join(str(value) for value in bounds) if isinstance(bounds, list) else "unknown"
        table.add_row(
            str(node.get("index", "?")),
            str(node.get("parent_index", "-")),
            str(node.get("control_type", "unknown")),
            str(node.get("class_name", "unknown")),
            str(node.get("automation_id", "")),
            bounds_text,
            str(node.get("enabled", "unknown")),
        )
    console.print(table)
@app.command("learning-report")
def learning_report(
    limit: int = typer.Option(1000, min=1, max=1000),
) -> None:
    """Summarize user-reported diagnostic outcomes; does not retrain models."""
    from aie.learning.analytics import load_feedback_summary

    summaries = load_feedback_summary(EventStore(database_path()), limit=limit)
    if not summaries:
        console.print(
            "No user feedback recorded yet. Use aie feedback <EVENT_ID> "
            "--outcome resolved|not_resolved|not_attempted."
        )
        return

    table = Table("Diagnostic cause", "Resolved", "Not resolved", "Not attempted", "Observed resolution")
    for item in summaries:
        rate = "n/a" if item.resolution_rate is None else f"{item.resolution_rate:.0%}"
        table.add_row(
            item.cause,
            str(item.resolved),
            str(item.not_resolved),
            str(item.not_attempted),
            rate,
        )
    console.print(table)
    console.print("[dim]Resolution rates are descriptive user feedback, not causal proof or model-training metrics.[/dim]")



@app.command("remember")
def remember(
    content: str | None = typer.Argument(None, help="User-authored memory text; omit to enter it interactively."),
    kind: Literal["working", "episodic", "semantic", "procedural", "prospective"] = typer.Option("episodic"),
    tags: str = typer.Option("", help="Comma-separated local tags."),
    ttl_days: int | None = typer.Option(None, min=1, max=3650, help="Optional expiry in days."),
    sensitive: bool = typer.Option(False, help="Mark the memory sensitive; hidden from recall by default."),
    source_event_id: list[str] = typer.Option([], help="Optional event IDs used as provenance."),
) -> None:
    """Explicitly save a user-authored memory to the local memory database."""
    from aie.memory.models import MemoryRecord
    from aie.memory.store import MemoryStore

    if content is None:
        content = typer.prompt("Memory content", hide_input=sensitive)
    now = datetime.now(timezone.utc)
    memory = MemoryRecord(
        kind=kind,
        content=content,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        sensitivity="sensitive" if sensitive else "internal",
        source_event_ids=source_event_id,
        created_at=now,
        expires_at=now + timedelta(days=ttl_days) if ttl_days else None,
    )
    try:
        saved = MemoryStore(memory_database_path()).save(
            memory,
            event_store=EventStore(database_path()) if source_event_id else None,
        )
    except ValueError as exc:
        console.print(f"[red]Memory not saved:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"[green]Memory saved locally.[/green] ID: {saved.memory_id}")
    console.print(f"Kind: {saved.kind} · Sensitivity: {saved.sensitivity}")


@app.command("recall")
def recall(
    query: str = typer.Argument(..., help="Local keyword or semantic query."),
    kind: Literal["working", "episodic", "semantic", "procedural", "prospective"] | None = typer.Option(None),
    include_sensitive: bool = typer.Option(False, help="Explicitly include sensitive memories."),
    limit: int = typer.Option(10, min=1, max=100),
    semantic: bool = typer.Option(False, "--semantic/--lexical"),
    embedding_model: str = typer.Option("nomic-embed-text:latest"),
) -> None:
    """Retrieve memories using lexical overlap or local Ollama embeddings."""
    from aie.memory.store import MemoryStore

    store = MemoryStore(memory_database_path())
    try:
        if semantic:
            from aie.models.ollama import OllamaClient

            client = OllamaClient()
            vector = client.embed([query], model=embedding_model)[0]
            hits = store.search_semantic(
                vector,
                model=embedding_model,
                kind=kind,
                include_sensitive=include_sensitive,
                limit=limit,
            )
        else:
            hits = store.search(
                query,
                kind=kind,
                include_sensitive=include_sensitive,
                limit=limit,
            )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Memory retrieval unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc
    if not hits:
        console.print("No matching local memories.")
        return

    for index, hit in enumerate(hits, start=1):
        console.print(
            f"[bold]Result {index}[/bold] · {hit.memory.kind} · "
            f"Score {hit.score:.3f} · Tags: {', '.join(hit.memory.tags) or 'none'}"
        )
        console.print(f"Memory ID: {hit.memory.memory_id}")
        console.print(hit.memory.content)
        if index < len(hits):
            console.print()


@app.command("memories")
def memories(
    include_sensitive: bool = typer.Option(False),
    include_superseded: bool = typer.Option(False),
    limit: int = typer.Option(100, min=1, max=1000),
) -> None:
    """List local memories without exposing sensitive entries by default."""
    from aie.memory.store import MemoryStore

    items = MemoryStore(memory_database_path()).list_memories(
        include_sensitive=include_sensitive,
        include_superseded=include_superseded,
        limit=limit,
    )
    table = Table("Kind", "Status", "Sensitivity", "Expires", "Memory ID", "Content")
    for item in items:
        table.add_row(
            item.memory.kind,
            item.status,
            item.memory.sensitivity,
            item.memory.expires_at.isoformat() if item.memory.expires_at else "never",
            item.memory.memory_id,
            item.memory.content[:120],
        )
    console.print(table)
    console.print(f"Visible memories: {len(items)}")


@app.command("correct-memory")
def correct_memory(
    memory_id: str = typer.Argument(..., help="Active memory ID to supersede."),
    content: str = typer.Argument(..., help="Corrected memory text."),
) -> None:
    """Create a corrected memory while retaining the old version as superseded."""
    from aie.memory.models import MemoryRecord
    from aie.memory.store import MemoryStore

    store = MemoryStore(memory_database_path())
    previous = store.get(memory_id)
    if previous is None:
        console.print("[red]Active memory not found.[/red]")
        raise typer.Exit(2)
    expiry = previous.memory.expires_at
    if expiry is not None and expiry <= datetime.now(timezone.utc):
        expiry = None
    corrected = MemoryRecord(
        kind=previous.memory.kind,
        content=content,
        tags=previous.memory.tags,
        sensitivity=previous.memory.sensitivity,
        confidence=previous.memory.confidence,
        source_event_ids=previous.memory.source_event_ids,
        supersedes_id=memory_id,
        expires_at=expiry,
    )
    try:
        new_record = store.save(
            corrected,
            event_store=EventStore(database_path()) if corrected.source_event_ids else None,
        )
    except ValueError as exc:
        console.print(f"[red]Correction failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"[green]Corrected memory saved.[/green] New ID: {new_record.memory_id}")


@app.command("forget")
def forget_memory(
    memory_id: str = typer.Argument(...),
    confirm: bool = typer.Option(False, "--confirm", help="Permanently delete this memory."),
) -> None:
    """Preview or permanently delete one local memory."""
    from aie.memory.store import MemoryStore

    store = MemoryStore(memory_database_path())
    item = store.get(memory_id, include_superseded=True)
    if item is None:
        console.print("Memory not found.")
        return
    if not confirm:
        console.print(
            f"Memory {memory_id} exists ({item.status}, {item.memory.sensitivity}). "
            "Nothing was deleted. Re-run with --confirm."
        )
        return
    store.delete(memory_id)
    console.print(f"[green]Deleted memory {memory_id}.[/green]")



@app.command("memory-index")
def memory_index(
    model: str = typer.Option("nomic-embed-text:latest", help="Already-installed local Ollama embedding model."),
    batch_size: int = typer.Option(8, min=1, max=32),
    include_sensitive: bool = typer.Option(False, help="Explicitly index sensitive local memories."),
) -> None:
    """Create/update local semantic embeddings; never downloads a model."""
    from aie.memory.semantic import index_memory_embeddings
    from aie.memory.store import MemoryStore
    from aie.models.ollama import OllamaClient

    if include_sensitive:
        console.print("[yellow]Sensitive memory indexing enabled. Embeddings are local but not encrypted; ensure the device account is protected.[/yellow]")

    try:
        report = index_memory_embeddings(
            MemoryStore(memory_database_path()),
            OllamaClient(),
            model=model,
            batch_size=batch_size,
            include_sensitive=include_sensitive,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Memory indexing unavailable:[/red] {exc}")
        raise typer.Exit(2) from exc

    console.print(
        f"[green]Memory index updated.[/green] Model: {report.model} · "
        f"Eligible: {report.eligible_memories} · "
        f"Already indexed: {report.already_indexed} · "
        f"New vectors: {report.indexed_now}"
    )


@app.command("memory-prune")
def memory_prune(
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Preview or delete expired local memory records."""
    from aie.memory.store import MemoryStore

    store = MemoryStore(memory_database_path())
    now = datetime.now(timezone.utc)
    expired_count = store.count_expired(now=now)
    if not confirm:
        console.print(f"{expired_count} expired memory record(s); nothing deleted.")
        return
    deleted = store.prune_expired(now=now)
    console.print(f"[green]Pruned {deleted} expired memory record(s).[/green]")




def _load_local_policy_broker():
    from aie.policy.broker import CapabilityPolicyBroker
    from aie.policy.manifests import load_capability_manifests

    manifests = load_capability_manifests(capability_manifest_dir())
    return CapabilityPolicyBroker(manifests), manifests


def _render_proposal(snapshot) -> None:
    status_color = {
        "pending_review": "yellow",
        "approved": "green",
        "rejected": "red",
        "blocked": "red",
    }.get(snapshot.status, "white")
    console.print(
        f"[bold]{snapshot.proposal.proposal_id}[/bold] · "
        f"{snapshot.proposal.capability_id} · "
        f"[{status_color}]{snapshot.status}[/{status_color}]"
    )
    console.print(snapshot.proposal.summary)
    console.print(
        f"Risk: {snapshot.risk_tier or 'unknown'} · "
        f"Policy allowed: {snapshot.policy_allowed} · "
        f"Approval required: {snapshot.approval_required}"
    )
    console.print(snapshot.reason)
    console.print("[dim]Execution: not implemented; no action was performed.[/dim]")


@app.command("capabilities")
def list_capabilities() -> None:
    """List locally authored capability manifests; no built-in capability is enabled."""
    from aie.policy.manifests import CapabilityManifestLoadError

    try:
        _, manifests = _load_local_policy_broker()
    except CapabilityManifestLoadError as exc:
        console.print(f"[red]Capability manifests rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    if not manifests:
        console.print(
            f"No capability manifests found in {capability_manifest_dir()}. "
            "Unknown capabilities remain denied."
        )
        return
    table = Table("Capability", "Risk", "Enabled", "Approval", "Allowed parameters")
    for manifest in manifests:
        table.add_row(
            manifest.capability_id,
            manifest.risk_tier,
            str(manifest.enabled),
            str(manifest.approval_required),
            ", ".join(sorted(manifest.allowed_parameters)),
        )
    console.print(table)


@app.command("propose")
def propose_action(
    capability_id: str = typer.Argument(...),
    summary: str = typer.Argument(..., help="Short human-readable action summary."),
    parameters_json: str = typer.Option("{}", "--parameters", help="Flat JSON object of allowlisted parameters."),
) -> None:
    """Queue an action proposal for policy evaluation and explicit user review."""
    import json

    from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
    from aie.policy.manifests import CapabilityManifestLoadError
    from aie.policy.models import ActionProposal

    try:
        parameters = json.loads(parameters_json)
        if not isinstance(parameters, dict):
            raise ValueError("--parameters must decode to a JSON object")
        proposal = ActionProposal(
            capability_id=capability_id,
            summary=summary,
            parameters=parameters,
            source="user",
        )
        broker, _ = _load_local_policy_broker()
        snapshot = PolicyProposalQueue(
            PolicyLedger(policy_audit_database_path())
        ).create(proposal, broker)
    except (ValueError, CapabilityManifestLoadError) as exc:
        console.print(f"[red]Proposal not queued:[/red] {exc}")
        raise typer.Exit(2) from exc
    _render_proposal(snapshot)


@app.command("proposals")
def list_proposals(
    status: Literal["all", "pending_review", "approved", "rejected", "blocked"] = typer.Option("pending_review"),
    limit: int = typer.Option(100, min=1, max=1000),
) -> None:
    """List proposal review states without displaying raw parameter payloads."""
    from aie.policy.ledger import PolicyLedger
    from aie.policy.manifests import CapabilityManifestLoadError

    try:
        _load_local_policy_broker()
        ledger = PolicyLedger(policy_audit_database_path())
        snapshots = ledger.list(
            status=None if status == "all" else status,
            limit=limit,
        )
    except CapabilityManifestLoadError as exc:
        console.print(f"[red]Capability manifests rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    if not snapshots:
        console.print("No proposals match that status.")
        return
    table = Table("Capability", "Status", "Risk", "Summary", "Updated")
    for item in snapshots:
        console.print(f"Proposal ID: {item.proposal.proposal_id}")
        table.add_row(
            item.proposal.capability_id,
            item.status,
            item.risk_tier or "unknown",
            item.proposal.summary[:100],
            item.updated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        )
    console.print(table)


def _review_queued_proposal(proposal_id: str, *, approve: bool) -> None:
    from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
    from aie.policy.manifests import CapabilityManifestLoadError

    try:
        broker, _ = _load_local_policy_broker()
        queue = PolicyProposalQueue(PolicyLedger(policy_audit_database_path()))
        snapshot = queue.review(proposal_id, approve=approve, broker=broker)
    except (ValueError, CapabilityManifestLoadError) as exc:
        console.print(f"[red]Proposal review failed:[/red] {exc}")
        raise typer.Exit(2) from exc
    _render_proposal(snapshot)


@app.command("approve-proposal")
def approve_proposal(proposal_id: str = typer.Argument(...)) -> None:
    """Record explicit local-user approval after re-evaluating current capability policy."""
    _review_queued_proposal(proposal_id, approve=True)


@app.command("reject-proposal")
def reject_proposal(proposal_id: str = typer.Argument(...)) -> None:
    """Record explicit local-user rejection; no action is executed."""
    _review_queued_proposal(proposal_id, approve=False)


@app.command("proposal-audit")
def proposal_audit(proposal_id: str = typer.Argument(...)) -> None:
    """Show the append-only review history without dumping proposal parameters."""
    from aie.policy.ledger import PolicyLedger

    ledger = PolicyLedger(policy_audit_database_path())
    integrity = ledger.verify_integrity()
    trail = ledger.audit_trail(proposal_id)
    if not trail:
        console.print("Proposal not found.")
        return
    table = Table("Sequence", "Event", "Timestamp", "Status", "Policy allowed", "Reason")
    for event in trail:
        payload = event["payload"]
        policy = payload.get("policy", {})
        table.add_row(
            str(event["sequence"]),
            event["event_type"],
            event["timestamp"],
            str(payload.get("status", "created")),
            str(policy.get("allowed", False)),
            str(policy.get("reason", ""))[:160],
        )
    console.print(table)
    integrity_text = (
        f"verified ({integrity.checked_entries} entries)"
        if integrity.valid
        else f"FAILED at sequence {integrity.first_invalid_sequence}: {integrity.reason}"
    )
    console.print(f"Audit chain: {integrity_text}")
    console.print("[dim]No execution records exist because the executor is not implemented.[/dim]")




@app.command("policy-audit-check")
def policy_audit_check() -> None:
    """Verify the complete SHA-256 chain in the local policy audit database."""
    from aie.policy.ledger import PolicyLedger

    report = PolicyLedger(policy_audit_database_path()).verify_integrity()
    if report.valid:
        console.print(
            f"[green]Policy audit chain verified.[/green] "
            f"{report.checked_entries} entries checked."
        )
        return
    console.print(
        f"[red]Policy audit integrity failure.[/red] "
        f"Sequence {report.first_invalid_sequence}: {report.reason}"
    )
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
