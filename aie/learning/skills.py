"""Reviewable procedural-skill candidates from explicitly verified task runs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aie.memory.models import MemoryRecord
from aie.orchestration.models import TaskRun
from aie.orchestration.store import TaskRunStore
from aie.policy.ledger import PolicyLedger
from aie.planning.validator import validate_plan


class SkillInductionError(ValueError):
    """Raised when a task run is not suitable for reviewed skill induction."""


class SkillCandidate(BaseModel):
    """Deterministic, review-only procedural memory drafted from one verified run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_run_id: str
    plan_id: str
    goal: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=8000)
    tags: tuple[str, ...] = Field(min_length=2, max_length=20)
    verified_step_ids: tuple[str, ...]
    proposal_ids: tuple[str, ...] = ()

    def to_memory_record(self, *, sensitivity: str = "sensitive") -> MemoryRecord:
        """Convert only after the CLI/user has reviewed and explicitly accepted it."""
        return MemoryRecord(
            kind="procedural",
            content=self.content,
            tags=list(self.tags),
            sensitivity=sensitivity,  # type: ignore[arg-type]
            confidence=1.0,
            source_task_run_ids=[self.task_run_id],
        )


def _ancestors(step_id: str, dependencies: dict[str, tuple[str, ...]]) -> set[str]:
    found: set[str] = set()
    pending = list(dependencies.get(step_id, ()))
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(dependencies.get(current, ()))
    return found


def build_skill_candidate(
    run: TaskRun,
    *,
    policy_ledger: PolicyLedger | None = None,
) -> SkillCandidate:
    """Require a completed run and a positive human/application verification step.

    Action steps additionally require successful immutable execution receipts, and
    every verified postcondition step must depend transitively on every action step.
    No model is used to summarize or rewrite the procedure.
    """
    if run.status != "completed":
        raise SkillInductionError("only completed task runs can produce skill candidates")
    validate_plan(run.plan)

    plan_steps = {step.step_id: step for step in run.plan.steps}
    states = {state.step_id: state for state in run.steps}
    if set(plan_steps) != set(states):
        raise SkillInductionError("task state does not match the plan")
    if any(states[step_id].status != "completed" for step_id in plan_steps):
        raise SkillInductionError("every task step must be completed")

    verified_ids = tuple(
        step.step_id
        for step in run.plan.steps
        if step.kind == "verify"
        and states[step.step_id].verified
        and states[step.step_id].status == "completed"
    )
    if not verified_ids:
        raise SkillInductionError(
            "at least one verify step must have an explicit positive verification result"
        )

    action_steps = [
        step for step in run.plan.steps if step.kind == "propose_action"
    ]
    proposal_ids: list[str] = []
    if action_steps:
        if policy_ledger is None:
            raise SkillInductionError("policy ledger is required for action-bearing runs")
        integrity = policy_ledger.verify_integrity()
        if not integrity.valid:
            raise SkillInductionError("policy audit chain is invalid")
        for step in action_steps:
            state = states[step.step_id]
            if not state.proposal_id:
                raise SkillInductionError("completed action step is missing its proposal ID")
            snapshot = policy_ledger.get(state.proposal_id)
            if (
                snapshot is None
                or snapshot.status != "approved"
                or snapshot.execution_status != "succeeded"
                or not snapshot.action_executed
            ):
                raise SkillInductionError(
                    "every action step requires a successful execution receipt"
                )
            proposal_ids.append(state.proposal_id)

        dependencies = {
            step.step_id: tuple(step.depends_on) for step in run.plan.steps
        }
        for verified_step_id in verified_ids:
            ancestors = _ancestors(verified_step_id, dependencies)
            if not {step.step_id for step in action_steps}.issubset(ancestors):
                raise SkillInductionError(
                    "a positive verification step must depend on every action step"
                )

    lines = [
        f"Goal: {run.plan.goal}",
        "",
        "Procedure:",
    ]
    for index, step in enumerate(run.plan.steps, start=1):
        state = states[step.step_id]
        if step.kind == "inform":
            continue
        lines.append(f"{index}. [{step.kind}] {step.description}")
        lines.append(f"   Success criteria: {step.success_criteria}")
        if state.summary:
            lines.append(f"   Recorded outcome: {state.summary[:220]}")
    lines.extend(["", "Verified postconditions:"])
    for step_id in verified_ids:
        step = plan_steps[step_id]
        summary = states[step_id].summary or "Explicit verification recorded."
        lines.append(f"- {step.success_criteria} Outcome: {summary[:220]}")
    if proposal_ids:
        lines.extend([
            "",
            "Policy execution receipts:",
            *[f"- {proposal_id}" for proposal_id in proposal_ids],
        ])
    content = "\n".join(lines)
    if len(content) > 8000:
        raise SkillInductionError(
            "the generated procedural summary exceeds the memory size limit"
        )

    tags = ["skill", "procedural", "verified", f"run-{run.run_id[:30]}"]
    for step in run.plan.steps:
        if step.kind not in {"inform"} and step.kind not in tags and len(tags) < 20:
            tags.append(step.kind)
    return SkillCandidate(
        task_run_id=run.run_id,
        plan_id=run.plan.plan_id,
        goal=run.plan.goal,
        content=content,
        tags=tuple(tags),
        verified_step_ids=verified_ids,
        proposal_ids=tuple(proposal_ids),
    )


def save_skill_candidate(
    candidate: SkillCandidate,
    *,
    memory_store,
    task_run_store: TaskRunStore,
    policy_ledger: PolicyLedger | None = None,
    sensitivity: str = "sensitive",
) -> MemoryRecord:
    """Persist a reviewed candidate as procedural memory with task-run provenance."""
    source = task_run_store.get(candidate.task_run_id)
    if source is None or source.status != "completed":
        raise SkillInductionError("source task run must still exist and be completed")
    rebuilt = build_skill_candidate(source, policy_ledger=policy_ledger)
    if rebuilt != candidate:
        raise SkillInductionError(
            "candidate does not match the persisted task run and audit evidence"
        )
    record = candidate.to_memory_record(sensitivity=sensitivity)
    return memory_store.save(record, task_run_store=task_run_store)
