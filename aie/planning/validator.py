"""Deterministic validation and readiness queries for declarative plans."""
from __future__ import annotations

from dataclasses import dataclass

from aie.planning.models import PlanStep, TaskPlan


class PlanValidationError(ValueError):
    """Raised when a plan dependency graph cannot be safely scheduled."""


@dataclass(frozen=True, slots=True)
class PlanValidation:
    plan_id: str
    ordered_step_ids: tuple[str, ...]


def validate_plan(plan: TaskPlan) -> PlanValidation:
    """Return a stable topological order or reject a cyclic dependency graph.

    Among simultaneously-ready steps, original plan order is preserved. This makes
    validation deterministic without pretending that the order expresses priority,
    user intent, or a causal relationship.
    """
    positions = {step.step_id: index for index, step in enumerate(plan.steps)}
    by_id = {step.step_id: step for step in plan.steps}
    indegree = {step.step_id: len(step.depends_on) for step in plan.steps}
    dependents: dict[str, list[str]] = {step.step_id: [] for step in plan.steps}

    for step in plan.steps:
        for dependency in step.depends_on:
            dependents[dependency].append(step.step_id)

    ready = sorted(
        (step_id for step_id, degree in indegree.items() if degree == 0),
        key=positions.__getitem__,
    )
    ordered: list[str] = []

    while ready:
        step_id = ready.pop(0)
        ordered.append(step_id)
        for dependent in sorted(dependents[step_id], key=positions.__getitem__):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort(key=positions.__getitem__)

    if len(ordered) != len(by_id):
        blocked = sorted(
            (step_id for step_id, degree in indegree.items() if degree > 0),
            key=positions.__getitem__,
        )
        raise PlanValidationError(
            "dependency graph contains a cycle involving: " + ", ".join(blocked)
        )

    return PlanValidation(plan_id=plan.plan_id, ordered_step_ids=tuple(ordered))


def next_ready_steps(
    plan: TaskPlan,
    *,
    completed_step_ids: set[str] | frozenset[str] = frozenset(),
) -> tuple[PlanStep, ...]:
    """Return unfinished steps whose dependencies are complete, in stable plan order.

    Completion IDs are supplied by the caller and are not inferred from model output.
    This function reports readiness only; it does not start a step or invoke a tool.
    """
    known_ids = {step.step_id for step in plan.steps}
    unknown = set(completed_step_ids) - known_ids
    if unknown:
        raise ValueError("unknown completed step IDs: " + ", ".join(sorted(unknown)))

    ordered = validate_plan(plan).ordered_step_ids
    by_id = {step.step_id: step for step in plan.steps}
    completed = set(completed_step_ids)
    ready: list[PlanStep] = []

    for step_id in ordered:
        step = by_id[step_id]
        if step_id not in completed and set(step.depends_on).issubset(completed):
            ready.append(step)

    return tuple(ready)
