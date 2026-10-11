"""CLI commands for plan drafting and resumable task orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from aie.config import (
    capability_manifest_dir,
    database_path,
    memory_database_path,
    policy_audit_database_path,
    task_run_database_path,
)
from aie.models.ollama import OllamaClient
from aie.models.router import LocalModelRouter
from aie.orchestration.agent import start_agent_run
from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.handlers import build_default_handlers
from aie.orchestration.store import TaskRunStore
from aie.planning.generator import generate_plan
from aie.planning.models import TaskPlan
from aie.planning.validator import validate_plan
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger
from aie.policy.manifests import load_capability_manifests
from aie.store import EventStore

plan_app = typer.Typer(no_args_is_help=True, help="Draft and validate bounded task plans.")
task_app = typer.Typer(no_args_is_help=True, help="Create, advance and inspect durable task runs.")
agent_app = typer.Typer(no_args_is_help=True, help="Run a bounded local agent task.")
console = Console()


def _load_plan(path: Path) -> TaskPlan:
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("plan path must point to a regular local file")
        if path.stat().st_size > 128 * 1024:
            raise ValueError("plan file exceeds 128 KiB")
        return TaskPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise typer.BadParameter(f"invalid plan file ({type(exc).__name__}): {exc}") from exc


def _engine() -> TaskOrchestrator:
    return TaskOrchestrator(TaskRunStore(task_run_database_path()))


@plan_app.command("validate")
def validate_plan_file(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Validate a JSON plan and display its deterministic dependency order."""
    plan = _load_plan(path)
    result = validate_plan(plan)
    table = Table("Order", "Step ID", "Kind", "Dependencies")
    by_id = {step.step_id: step for step in plan.steps}
    for index, step_id in enumerate(result.ordered_step_ids, start=1):
        step = by_id[step_id]
        table.add_row(
            str(index),
            step.step_id,
            step.kind,
            ", ".join(step.depends_on) or "-",
        )
    console.print(f"Plan: {plan.plan_id}")
    console.print(f"Goal: {plan.goal}")
    console.print(table)


@plan_app.command("draft")
def draft_plan(
    goal: str = typer.Argument(..., help="The user's requested outcome."),
    model: str = typer.Option(..., "--model", help="An already-installed local Ollama model."),
    output: Path = typer.Option(Path("task-plan.json"), "--output"),
    capability_id: list[str] = typer.Option(
        [], "--capability-id", help="Capability IDs that the plan may reference."
    ),
    context_file: Path | None = typer.Option(
        None, "--context-file", help="Optional user-selected context file; never collected automatically."
    ),
) -> None:
    """Draft a JSON plan using local Ollama, then validate it before saving."""
    explicit_context = None
    if context_file is not None:
        if context_file.is_symlink() or not context_file.is_file():
            raise typer.BadParameter("context file must be a regular local file")
        if context_file.stat().st_size > 24 * 1024:
            raise typer.BadParameter("context file exceeds 24 KiB")
        explicit_context = context_file.read_text(encoding="utf-8")
    try:
        plan = generate_plan(
            goal,
            provider=OllamaClient(),
            model=model,
            allowed_capability_ids=set(capability_id),
            explicit_context=explicit_context,
        )
        validate_plan(plan)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - report bounded local planning errors.
        console.print(f"[red]Plan drafting failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(2) from exc
    console.print(f"[green]Validated plan saved:[/green] {output}")
    console.print(f"Plan ID: {plan.plan_id} · Steps: {len(plan.steps)}")


@agent_app.command("run")
def run_agent(
    goal: str = typer.Argument(..., help="The outcome the assistant should work toward."),
    model: str = typer.Option(..., "--model", help="An already-installed local Ollama model."),
    capability_id: list[str] = typer.Option(
        [],
        "--capability-id",
        help="Explicit capability IDs the drafted plan may reference; none are allowed by default.",
    ),
    setting: Literal[
        "display", "sound", "bluetooth", "network",
        "windows_update", "apps", "privacy"
    ] | None = typer.Option(
        None,
        "--setting",
        help="Explicit page choice for windows.settings.open proposals.",
    ),
    max_steps: int = typer.Option(5, "--max-steps", min=1, max=25),
    with_memory: bool = typer.Option(
        False, "--with-memory", help="Explicitly attach bounded local memory to reasoning."
    ),
    include_sensitive_memory: bool = typer.Option(
        False, "--include-sensitive-memory", help="Also retrieve sensitive memories."
    ),
    semantic_memory: bool = typer.Option(
        False, "--semantic-memory", help="Use an already-installed local embedding model."
    ),
    embedding_model: str = typer.Option("nomic-embed-text:latest", "--embedding-model"),
    memory_limit: int = typer.Option(5, "--memory-limit", min=1, max=10),
    context_file: Path | None = typer.Option(
        None, "--context-file", help="Optional user-selected context file; never read implicitly."
    ),
) -> None:
    """Draft a local plan, persist its run and advance safe steps until a gate is reached."""
    if include_sensitive_memory and not with_memory:
        raise typer.BadParameter("--include-sensitive-memory requires --with-memory")
    if semantic_memory and not with_memory:
        raise typer.BadParameter("--semantic-memory requires --with-memory")
    if context_file is not None:
        if context_file.is_symlink() or not context_file.is_file():
            raise typer.BadParameter("context file must be a regular local file")
        if context_file.stat().st_size > 24 * 1024:
            raise typer.BadParameter("context file exceeds 24 KiB")
    explicit_context = (
        context_file.read_text(encoding="utf-8") if context_file is not None else None
    )

    try:
        provider = OllamaClient()
        engine = _engine()
        launch = start_agent_run(
            goal,
            provider=provider,
            model=model,
            orchestrator=engine,
            allowed_capability_ids=set(capability_id),
            explicit_context=explicit_context,
        )
        manifests = load_capability_manifests(capability_manifest_dir())
        broker = CapabilityPolicyBroker(manifests)
        ledger = PolicyLedger(policy_audit_database_path())

        memory_context_builder = None
        if with_memory:
            from aie.memory.prompt_context import build_memory_prompt_context
            from aie.memory.store import MemoryStore

            embedding_client = OllamaClient() if semantic_memory else None

            def memory_context_builder(query: str):
                return build_memory_prompt_context(
                    query,
                    MemoryStore(memory_database_path()),
                    include_sensitive=include_sensitive_memory,
                    limit=memory_limit,
                    semantic_model=embedding_model if semantic_memory else None,
                    embedding_provider=embedding_client,
                )

        handlers = build_default_handlers(
            event_store=EventStore(database_path()),
            broker=broker,
            ledger=ledger,
            model_router=LocalModelRouter(provider),
            proposal_parameters=(
                {"windows.settings.open": {"setting": setting}}
                if setting is not None
                else {}
            ),
            memory_context_builder=memory_context_builder,
        )
        advanced = engine.advance(
            launch.run.run_id,
            handlers,
            max_steps=max_steps,
        )
    except Exception as exc:  # noqa: BLE001 - errors are bounded; no external provider payload is persisted.
        console.print(f"[red]Agent run failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(2) from exc

    console.print(
        f"[bold]P1- task[/bold] · Run: {advanced.run_id} · "
        f"State: {advanced.status} · Version: {advanced.version}"
    )
    console.print(f"Goal: {advanced.plan.goal}")
    console.print(f"Plan: {advanced.plan.plan_id} · Steps: {len(advanced.steps)}")
    table = Table("Step", "Kind", "State", "Attempts", "Proposal")
    plan_steps = {item.step_id: item for item in advanced.plan.steps}
    for state in advanced.steps:
        table.add_row(
            state.step_id,
            plan_steps[state.step_id].kind,
            state.status,
            str(state.attempts),
            state.proposal_id or "-",
        )
    console.print(table)
    if advanced.status == "awaiting_approval":
        console.print("[yellow]Review the pending proposal with aie proposals, then approve it explicitly.[/yellow]")
    elif advanced.status == "awaiting_input":
        console.print("[yellow]User input or verification is required. Inspect the run with aie task show.[/yellow]")
    elif advanced.status == "completed":
        console.print("[green]All plan steps reached their recorded completion states.[/green]")
    console.print(f"Continue with: aie task advance {advanced.run_id} --max-steps 3")


@task_app.command("start")
def start_task(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Create a durable task run from a previously validated JSON plan."""
    plan = _load_plan(path)
    run = _engine().create(plan)
    console.print(f"[green]Task run created.[/green] Run ID: {run.run_id}")
    console.print(f"Plan: {plan.plan_id} · State: {run.status}")


@task_app.command("list")
def list_tasks(limit: int = typer.Option(50, min=1, max=1000)) -> None:
    """List recent task runs without dumping their full plan or context."""
    runs = TaskRunStore(task_run_database_path()).list(limit=limit)
    if not runs:
        console.print("No task runs found.")
        return
    table = Table("Run ID", "Status", "Completed", "Steps", "Updated")
    for run in runs:
        completed = sum(step.status == "completed" for step in run.steps)
        table.add_row(
            run.run_id,
            run.status,
            str(completed),
            str(len(run.steps)),
            run.updated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        )
    console.print(table)


@task_app.command("show")
def show_task(run_id: str = typer.Argument(...)) -> None:
    """Show step states and bounded summaries for one task run."""
    try:
        run = _engine().get(run_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"Run: {run.run_id} · Status: {run.status} · Version: {run.version}")
    console.print(f"Goal: {run.plan.goal}")
    table = Table("Step", "Kind", "State", "Attempts", "Verified", "Proposal")
    plan_steps = {item.step_id: item for item in run.plan.steps}
    for state in run.steps:
        step = plan_steps[state.step_id]
        table.add_row(
            step.step_id,
            step.kind,
            state.status,
            str(state.attempts),
            str(state.verified),
            state.proposal_id or "-",
        )
        if state.summary:
            console.print(f"[dim]{step.step_id}:[/dim] {state.summary}")
    console.print(table)
    if run.failure_type:
        console.print(f"[red]Failure type:[/red] {run.failure_type}")


@task_app.command("events")
def task_events(
    run_id: str = typer.Argument(...),
    limit: int = typer.Option(100, min=1, max=2000),
) -> None:
    """Inspect the append-only lifecycle journal for one run."""
    events = TaskRunStore(task_run_database_path()).events(run_id, limit=limit)
    if not events:
        console.print("No task events found.")
        return
    table = Table("Seq", "Version", "Event", "Timestamp", "Details")
    for event in events:
        table.add_row(
            str(event["sequence"]),
            str(event["version"]),
            event["event_type"],
            event["timestamp"],
            json.dumps(event["payload"], ensure_ascii=True)[:220],
        )
    console.print(table)


@task_app.command("advance")
def advance_task(
    run_id: str = typer.Argument(...),
    max_steps: int = typer.Option(1, "--max-steps", min=1, max=25),
    setting: Literal[
        "display", "sound", "bluetooth", "network",
        "windows_update", "apps", "privacy"
    ] | None = typer.Option(
        None,
        "--setting",
        help="Explicit page choice for the built-in windows.settings.open capability.",
    ),
    with_memory: bool = typer.Option(
        False, "--with-memory", help="Explicitly attach bounded local memory to reasoning."
    ),
    include_sensitive_memory: bool = typer.Option(
        False, "--include-sensitive-memory", help="Also retrieve sensitive memories."
    ),
    semantic_memory: bool = typer.Option(
        False, "--semantic-memory", help="Use an already-installed local embedding model."
    ),
    embedding_model: str = typer.Option("nomic-embed-text:latest", "--embedding-model"),
    memory_limit: int = typer.Option(5, "--memory-limit", min=1, max=10),
) -> None:
    """Advance ready steps using local observation, local model and policy handlers."""
    try:
        manifests = load_capability_manifests(capability_manifest_dir())
        broker = CapabilityPolicyBroker(manifests)
        ledger = PolicyLedger(policy_audit_database_path())
        trusted_parameters = (
            {"windows.settings.open": {"setting": setting}}
            if setting is not None
            else {}
        )
        if include_sensitive_memory and not with_memory:
            raise ValueError("--include-sensitive-memory requires --with-memory")
        if semantic_memory and not with_memory:
            raise ValueError("--semantic-memory requires --with-memory")

        memory_context_builder = None
        if with_memory:
            from aie.memory.prompt_context import build_memory_prompt_context
            from aie.memory.store import MemoryStore

            embedding_client = OllamaClient() if semantic_memory else None

            def memory_context_builder(query: str):
                return build_memory_prompt_context(
                    query,
                    MemoryStore(memory_database_path()),
                    include_sensitive=include_sensitive_memory,
                    limit=memory_limit,
                    semantic_model=embedding_model if semantic_memory else None,
                    embedding_provider=embedding_client,
                )

        handlers = build_default_handlers(
            event_store=EventStore(database_path()),
            broker=broker,
            ledger=ledger,
            model_router=LocalModelRouter(OllamaClient()),
            proposal_parameters=trusted_parameters,
            memory_context_builder=memory_context_builder,
        )
        run = _engine().advance(run_id, handlers, max_steps=max_steps)
    except Exception as exc:  # noqa: BLE001 - do not leak provider payloads into task state.
        console.print(f"[red]Task advance failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Run {run.run_id} · State: {run.status} · Version: {run.version}")
    for item in run.steps:
        console.print(f"  {item.step_id}: {item.status}")


@task_app.command("complete")
def complete_task_step(
    run_id: str = typer.Argument(...),
    step_id: str = typer.Argument(...),
    summary: str = typer.Option(..., "--summary", help="Explicit result or verification note."),
    verified: bool = typer.Option(
        False, "--verified", help="Assert a postcondition was manually checked."
    ),
) -> None:
    """Record a human result; verify steps require the explicit --verified flag."""
    try:
        run = _engine().complete_input(
            run_id,
            step_id,
            summary=summary,
            verified=verified,
        )
    except ValueError as exc:
        console.print(f"[red]Task input rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Run {run.run_id} · State: {run.status}")


def _change_task_state(run_id: str, operation: Literal["pause", "resume", "cancel"]) -> None:
    engine = _engine()
    try:
        run = getattr(engine, operation)(run_id)
    except ValueError as exc:
        console.print(f"[red]Task transition rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(f"Run {run.run_id} · State: {run.status}")


@task_app.command("recover")
def recover_task(
    run_id: str = typer.Argument(...),
    confirm: bool = typer.Option(
        False, "--confirm", help="Confirm that the prior handler process is no longer active."
    ),
    after_seconds: int = typer.Option(
        300, "--after-seconds", min=1, max=86400,
        help="Minimum age of a still-running step before it can be recovered.",
    ),
) -> None:
    """Move a stale interrupted handler to explicit human review without replaying it."""
    if not confirm:
        console.print(
            "[yellow]Inspect the process first. Pass --confirm only after confirming "
            "the previous handler is no longer active.[/yellow]"
        )
        raise typer.Exit(2)
    try:
        run = _engine().recover_interrupted(
            run_id,
            minimum_age_seconds=after_seconds,
        )
    except ValueError as exc:
        console.print(f"[red]Recovery rejected:[/red] {exc}")
        raise typer.Exit(2) from exc
    console.print(
        f"[green]Run recovered for review.[/green] {run.run_id} · {run.status}"
    )
    for step in run.steps:
        if step.status == "awaiting_input":
            console.print(f"  {step.step_id}: inspect side effects and record an explicit result")


@task_app.command("pause")
def pause_task(run_id: str = typer.Argument(...)) -> None:
    """Pause a task between handler invocations."""
    _change_task_state(run_id, "pause")


@task_app.command("resume")
def resume_task(run_id: str = typer.Argument(...)) -> None:
    """Resume a paused task."""
    _change_task_state(run_id, "resume")


@task_app.command("cancel")
def cancel_task(run_id: str = typer.Argument(...)) -> None:
    """Cancel a queued or waiting task; active adapters must enforce their own deadlines."""
    _change_task_state(run_id, "cancel")
