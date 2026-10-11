"""Deterministic, resumable task orchestration; handlers are injected capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol

from aie.orchestration.models import StepRun, TaskRun
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan
from aie.planning.validator import next_ready_steps, validate_plan

HandlerStatus = Literal["completed", "awaiting_approval", "awaiting_input", "failed"]


@dataclass(frozen=True, slots=True)
class StepContext:
    """Minimal state passed to a step handler; never grants an action capability."""

    run_id: str
    plan_id: str
    goal: str
    attempt: int
    completed_step_ids: tuple[str, ...]
    prior_summaries: tuple[str, ...]
    proposal_id: str | None = None


@dataclass(frozen=True, slots=True)
class HandlerResult:
    status: HandlerStatus
    summary: str
    proposal_id: str | None = None
    verified: bool = False
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "completed", "awaiting_approval", "awaiting_input", "failed"
        }:
            raise ValueError("invalid handler result status")
        if not self.summary or len(self.summary) > 1000:
            raise ValueError("handler summary must contain 1 to 1000 characters")
        if self.status == "awaiting_approval" and not self.proposal_id:
            raise ValueError("approval-waiting results require a proposal_id")
        if self.verified and self.status != "completed":
            raise ValueError("only completed handler results may be verified")
        if self.status == "failed" and not self.error_type:
            raise ValueError("failed handler results require an error_type")

    @classmethod
    def completed(cls, summary: str, *, verified: bool = False) -> "HandlerResult":
        return cls(status="completed", summary=summary, verified=verified)

    @classmethod
    def awaiting_approval(cls, proposal_id: str, summary: str) -> "HandlerResult":
        return cls(
            status="awaiting_approval",
            summary=summary,
            proposal_id=proposal_id,
        )

    @classmethod
    def awaiting_input(cls, summary: str) -> "HandlerResult":
        return cls(status="awaiting_input", summary=summary)

    @classmethod
    def failed(cls, error_type: str, summary: str) -> "HandlerResult":
        return cls(status="failed", summary=summary, error_type=error_type)


class StepHandler(Protocol):
    def execute(self, step: PlanStep, context: StepContext) -> HandlerResult:
        """Execute one bounded step and return an explicit outcome."""
        ...


class TaskOrchestrator:
    """Persist and advance validated plans one handler invocation at a time.

    The orchestrator has no implicit tool access. Every step kind must be mapped to an
    application-owned handler. A model response is never itself an approval or proof
    that a postcondition is true.
    """

    def __init__(self, store: TaskRunStore, *, policy_ledger=None) -> None:
        self.store = store
        self.policy_ledger = policy_ledger

    def create(self, plan: TaskPlan) -> TaskRun:
        validate_plan(plan)
        from aie.orchestration.models import new_task_run

        return self.store.create(new_task_run(plan))

    def get(self, run_id: str) -> TaskRun:
        run = self.store.get(run_id)
        if run is None:
            raise ValueError("task run was not found")
        return run

    @staticmethod
    def _step(run: TaskRun, step_id: str) -> StepRun:
        for item in run.steps:
            if item.step_id == step_id:
                return item
        raise ValueError(f"step {step_id!r} does not exist in this task run")

    @staticmethod
    def _replace_step(run: TaskRun, replacement: StepRun) -> TaskRun:
        steps = tuple(
            replacement if item.step_id == replacement.step_id else item
            for item in run.steps
        )
        return run.model_copy(update={"steps": steps})

    def pause(self, run_id: str) -> TaskRun:
        run = self.get(run_id)
        if run.status in {"completed", "failed", "cancelled", "paused"}:
            raise ValueError(f"cannot pause a task run in state {run.status!r}")
        if any(item.status == "running" for item in run.steps):
            raise ValueError("cannot pause during a handler invocation; pause between steps")
        updated = run.model_copy(update={"status": "paused"})
        return self.store.save(
            updated,
            expected_version=run.version,
            event_type="task.paused",
        )

    def recover_interrupted(
        self,
        run_id: str,
        *,
        minimum_age_seconds: int = 300,
        now: datetime | None = None,
    ) -> TaskRun:
        """Move stale running steps to human review; never replay their handlers.

        A still-running task can only be recovered after the configured age threshold.
        A run already marked interrupted by the engine is eligible immediately.
        Action handlers use deterministic proposal IDs, so a proposal written just
        before a process crash can be discovered and reused rather than duplicated.
        """
        if isinstance(minimum_age_seconds, bool) or not 1 <= minimum_age_seconds <= 86400:
            raise ValueError("minimum_age_seconds must be between 1 and 86400")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("recovery clock must be timezone-aware")
        current = current.astimezone(timezone.utc)

        run = self.get(run_id)
        already_failed_interrupted = (
            run.status == "failed"
            and run.failure_type == "interrupted_step_requires_review"
        )
        if run.status != "running" and not already_failed_interrupted:
            raise ValueError("only a running or interrupted task run can be recovered")

        active = [item for item in run.steps if item.status == "running"]
        if not active:
            raise ValueError("task run has no interrupted handler step to recover")

        if run.status == "running":
            for item in active:
                if item.started_at is None or item.started_at.tzinfo is None:
                    raise ValueError(
                        "running step has no trustworthy start time; inspect it manually"
                    )
                age = (current - item.started_at.astimezone(timezone.utc)).total_seconds()
                if age < minimum_age_seconds:
                    raise ValueError(
                        f"handler may still be active; wait at least "
                        f"{minimum_age_seconds - int(max(0, age))} more seconds"
                    )

        replacements = []
        for item in run.steps:
            if item.status != "running":
                replacements.append(item)
                continue
            replacements.append(
                item.model_copy(
                    update={
                        "status": "awaiting_input",
                        "summary": (
                            "Handler interruption detected. Inspect local side effects and "
                            "record the result explicitly; this handler will not be replayed."
                        ),
                        "verified": False,
                        "error_type": "interrupted_requires_review",
                        "completed_at": None,
                    }
                )
            )

        updated = run.model_copy(
            update={
                "status": "awaiting_input",
                "steps": tuple(replacements),
                "failure_type": None,
            }
        )
        return self.store.save(
            updated,
            expected_version=run.version,
            event_type="task.recovered_for_review",
            details={
                "step_ids": [item.step_id for item in active],
                "minimum_age_seconds": minimum_age_seconds,
            },
        )

    def resume(self, run_id: str) -> TaskRun:
        run = self.get(run_id)
        if run.status != "paused":
            raise ValueError("only paused task runs can be resumed")
        updated = run.model_copy(update={"status": "queued"})
        return self.store.save(
            updated,
            expected_version=run.version,
            event_type="task.resumed",
        )

    def cancel(self, run_id: str, *, reason: str = "cancelled by user") -> TaskRun:
        run = self.get(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            raise ValueError(f"cannot cancel a task run in state {run.status!r}")
        if any(item.status == "running" for item in run.steps):
            raise ValueError("cannot cancel during a handler invocation; cancel between steps")

        if self.policy_ledger is not None:
            for state in run.steps:
                if not state.proposal_id:
                    continue
                proposal = self.policy_ledger.get(state.proposal_id)
                if proposal is None or proposal.execution_status is not None:
                    continue
                if proposal.status in {"pending_review", "approved"}:
                    self.policy_ledger.append_revocation(
                        state.proposal_id,
                        reason=f"task run {run_id} was cancelled",
                    )

        now = datetime.now(timezone.utc)
        steps = tuple(
            item.model_copy(update={"status": "skipped", "completed_at": now})
            if item.status in {
                "pending", "running", "awaiting_approval", "awaiting_input"
            }
            else item
            for item in run.steps
        )
        updated = run.model_copy(
            update={"status": "cancelled", "steps": steps, "failure_type": None}
        )
        return self.store.save(
            updated,
            expected_version=run.version,
            event_type="task.cancelled",
            details={"reason": reason[:200]},
        )

    def retry_step(self, run_id: str, step_id: str) -> TaskRun:
        """Reset a waiting non-mutating step after its configuration is corrected."""
        run = self.get(run_id)
        if run.status != "awaiting_input":
            raise ValueError("task run is not awaiting user input")
        plan_step = next(
            (step for step in run.plan.steps if step.step_id == step_id),
            None,
        )
        if plan_step is None:
            raise ValueError(f"step {step_id!r} does not exist in this task run")
        if plan_step.kind not in {"observe", "reason", "inform"}:
            raise ValueError(
                "only observe, reason and inform steps can be explicitly retried; "
                "actions and verification use their own gates"
            )
        current = self._step(run, step_id)
        if current.status != "awaiting_input":
            raise ValueError("step is not awaiting user input")
        replacement = current.model_copy(
            update={
                "status": "pending",
                "summary": None,
                "error_type": None,
                "started_at": None,
                "completed_at": None,
                "verified": False,
                "proposal_id": None,
            }
        )
        updated = self._replace_step(run, replacement).model_copy(
            update={"status": "queued", "failure_type": None}
        )
        return self.store.save(
            updated,
            expected_version=run.version,
            event_type="task.step.retry_requested",
            details={"step_id": step_id, "kind": plan_step.kind},
        )

    def complete_input(
        self,
        run_id: str,
        step_id: str,
        *,
        summary: str,
        verified: bool = False,
    ) -> TaskRun:
        """Record explicit user input; verification steps require a positive assertion."""
        run = self.get(run_id)
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 1000:
            raise ValueError("summary must contain 1 to 1000 non-whitespace characters")
        if run.status != "awaiting_input":
            raise ValueError("task run is not awaiting user input")
        step_state = self._step(run, step_id)
        if step_state.status != "awaiting_input":
            raise ValueError("step is not awaiting user input")
        plan_step = next(step for step in run.plan.steps if step.step_id == step_id)
        if plan_step.kind == "propose_action":
            raise ValueError(
                "action steps can only complete from a policy-ledger execution receipt"
            )
        now = datetime.now(timezone.utc)
        if plan_step.kind == "verify" and not verified:
            replacement = step_state.model_copy(
                update={
                    "status": "failed",
                    "summary": summary[:1000],
                    "verified": False,
                    "error_type": "verification_not_confirmed",
                    "completed_at": now,
                }
            )
            updated = self._replace_step(run, replacement).model_copy(
                update={"status": "failed", "failure_type": "verification_not_confirmed"}
            )
            return self.store.save(
                updated,
                expected_version=run.version,
                event_type="task.step.verification_failed",
                details={"step_id": step_id},
            )

        replacement = step_state.model_copy(
            update={
                "status": "completed",
                "summary": summary[:1000],
                "verified": bool(verified),
                "completed_at": now,
                "error_type": None,
            }
        )
        updated = self._replace_step(run, replacement).model_copy(
            update={"status": "queued", "failure_type": None}
        )
        if all(item.status == "completed" for item in updated.steps):
            updated = updated.model_copy(update={"status": "completed"})
        return self.store.save(
            updated,
            expected_version=run.version,
            event_type="task.step.input_recorded",
            details={"step_id": step_id, "verified": bool(verified)},
        )

    def advance(
        self,
        run_id: str,
        handlers: dict[str, StepHandler],
        *,
        max_steps: int = 1,
    ) -> TaskRun:
        """Run up to max_steps synchronous handlers, persisting every transition."""
        if not 1 <= max_steps <= 25:
            raise ValueError("max_steps must be between 1 and 25")

        processed = 0
        run = self.get(run_id)
        if run.status in {"paused", "completed", "failed", "cancelled"}:
            return run
        if run.status == "awaiting_input" and not any(
            item.status == "awaiting_input"
            and next(step for step in run.plan.steps if step.step_id == item.step_id).kind == "propose_action"
            for item in run.steps
        ):
            return run

        while processed < max_steps:
            run = self.get(run_id)
            if run.status in {"paused", "completed", "failed", "cancelled"}:
                return run
            if run.status == "awaiting_input" and not any(
                item.status == "awaiting_input"
                and next(step for step in run.plan.steps if step.step_id == item.step_id).kind == "propose_action"
                for item in run.steps
            ):
                return run

            completed_ids = {
                item.step_id for item in run.steps if item.status == "completed"
            }
            ready = next_ready_steps(run.plan, completed_step_ids=completed_ids)
            candidates = [
                step for step in ready
                if self._step(run, step.step_id).status in {
                    "pending", "awaiting_approval"
                } or (
                    self._step(run, step.step_id).status == "awaiting_input"
                    and step.kind == "propose_action"
                )
            ]
            if not candidates:
                if all(item.status == "completed" for item in run.steps):
                    updated = run.model_copy(update={"status": "completed", "failure_type": None})
                    return self.store.save(
                        updated,
                        expected_version=run.version,
                        event_type="task.completed",
                    )
                waiting = any(
                    item.status in {"awaiting_approval", "awaiting_input"}
                    for item in run.steps
                )
                if waiting:
                    return run
                interrupted = any(item.status == "running" for item in run.steps)
                failure = "interrupted_step_requires_review" if interrupted else "no_ready_step"
                updated = run.model_copy(update={"status": "failed", "failure_type": failure})
                return self.store.save(
                    updated,
                    expected_version=run.version,
                    event_type="task.stopped",
                    details={"failure_type": failure},
                )

            plan_step = candidates[0]
            step_state = self._step(run, plan_step.step_id)
            handler = handlers.get(plan_step.kind)
            if handler is None:
                replacement = step_state.model_copy(
                    update={
                        "status": "awaiting_input",
                        "summary": "No handler is configured; explicit input is required.",
                        "started_at": step_state.started_at or datetime.now(timezone.utc),
                    }
                )
                updated = self._replace_step(run, replacement).model_copy(
                    update={"status": "awaiting_input"}
                )
                return self.store.save(
                    updated,
                    expected_version=run.version,
                    event_type="task.step.awaiting_input",
                    details={"step_id": plan_step.step_id, "reason": "handler_missing"},
                )

            now = datetime.now(timezone.utc)
            running_step = step_state.model_copy(
                update={
                    "status": "running",
                    "attempts": step_state.attempts + 1,
                    "started_at": now,
                    "error_type": None,
                }
            )
            running_run = self._replace_step(run, running_step).model_copy(
                update={"status": "running", "failure_type": None}
            )
            run = self.store.save(
                running_run,
                expected_version=run.version,
                event_type="task.step.started",
                details={"step_id": plan_step.step_id, "attempt": running_step.attempts},
            )

            current_state = self._step(run, plan_step.step_id)
            context = StepContext(
                run_id=run.run_id,
                plan_id=run.plan.plan_id,
                goal=run.plan.goal,
                attempt=current_state.attempts,
                completed_step_ids=tuple(sorted(completed_ids)),
                prior_summaries=tuple(
                    item.summary for item in run.steps
                    if item.status == "completed" and item.summary
                ),
                proposal_id=current_state.proposal_id,
            )
            try:
                result = handler.execute(plan_step, context)
                if not isinstance(result, HandlerResult):
                    raise TypeError("step handler must return HandlerResult")
            except Exception as exc:  # noqa: BLE001 - task state must record bounded failure metadata.
                result = HandlerResult.failed(
                    type(exc).__name__,
                    "Step handler failed; inspect local diagnostics before retrying.",
                )

            finished_at = datetime.now(timezone.utc)
            if result.status == "completed":
                if plan_step.kind == "verify" and not result.verified:
                    result = HandlerResult.failed(
                        "verification_not_confirmed",
                        "Verification handler did not provide a positive postcondition result.",
                    )

            if result.status == "completed":
                replacement = current_state.model_copy(
                    update={
                        "status": "completed",
                        "summary": result.summary,
                        "proposal_id": result.proposal_id or current_state.proposal_id,
                        "verified": result.verified,
                        "error_type": None,
                        "completed_at": finished_at,
                    }
                )
                updated = self._replace_step(run, replacement).model_copy(
                    update={"status": "running", "failure_type": None}
                )
                run = self.store.save(
                    updated,
                    expected_version=run.version,
                    event_type="task.step.completed",
                    details={
                        "step_id": plan_step.step_id,
                        "verified": result.verified,
                    },
                )
                processed += 1
                continue

            if result.status == "awaiting_approval":
                replacement = current_state.model_copy(
                    update={
                        "status": "awaiting_approval",
                        "summary": result.summary,
                        "proposal_id": result.proposal_id,
                        "verified": False,
                    }
                )
                updated = self._replace_step(run, replacement).model_copy(
                    update={"status": "awaiting_approval"}
                )
                return self.store.save(
                    updated,
                    expected_version=run.version,
                    event_type="task.step.awaiting_approval",
                    details={
                        "step_id": plan_step.step_id,
                        "proposal_id": result.proposal_id,
                    },
                )

            if result.status == "awaiting_input":
                replacement = current_state.model_copy(
                    update={
                        "status": "awaiting_input",
                        "summary": result.summary,
                        "verified": False,
                    }
                )
                updated = self._replace_step(run, replacement).model_copy(
                    update={"status": "awaiting_input"}
                )
                return self.store.save(
                    updated,
                    expected_version=run.version,
                    event_type="task.step.awaiting_input",
                    details={"step_id": plan_step.step_id},
                )

            replacement = current_state.model_copy(
                update={
                    "status": "failed",
                    "summary": result.summary,
                    "verified": False,
                    "error_type": result.error_type,
                    "completed_at": finished_at,
                }
            )
            updated = self._replace_step(run, replacement).model_copy(
                update={"status": "failed", "failure_type": result.error_type}
            )
            return self.store.save(
                updated,
                expected_version=run.version,
                event_type="task.step.failed",
                details={
                    "step_id": plan_step.step_id,
                    "error_type": result.error_type,
                },
            )

        run = self.get(run_id)
        if all(item.status == "completed" for item in run.steps):
            updated = run.model_copy(update={"status": "completed"})
            return self.store.save(
                updated,
                expected_version=run.version,
                event_type="task.completed",
            )
        return run
