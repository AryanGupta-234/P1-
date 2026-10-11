"""High-level local agent launch flow over the validated planner and task engine."""

from __future__ import annotations

from dataclasses import dataclass

from aie.models.base import ModelProvider
from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.models import TaskRun
from aie.planning.generator import generate_plan
from aie.planning.models import TaskPlan
from aie.planning.validator import validate_plan


@dataclass(frozen=True, slots=True)
class AgentLaunch:
    plan: TaskPlan
    run: TaskRun


def start_agent_run(
    goal: str,
    *,
    provider: ModelProvider,
    model: str,
    orchestrator: TaskOrchestrator,
    allowed_capability_ids: set[str] | frozenset[str] = frozenset(),
    explicit_context: str | None = None,
) -> AgentLaunch:
    """Draft, validate and persist a task run using only caller-selected inputs.

    This function does not observe the machine, attach memories, select tools or execute
    actions implicitly. Those operations belong to separately configured handlers and
    policy gates after the run has been created.
    """
    plan = generate_plan(
        goal,
        provider=provider,
        model=model,
        allowed_capability_ids=allowed_capability_ids,
        explicit_context=explicit_context,
    )
    validate_plan(plan)
    run = orchestrator.create(plan)
    return AgentLaunch(plan=plan, run=run)
