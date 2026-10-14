"""SQLite persistence for declarative plan runs and append-only step outcomes.

This store records workflow state only. It never invokes tools or executes plan steps.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from aie.planning.models import TaskPlan
from aie.planning.validator import validate_plan

StepStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
RunStatus = Literal["active", "completed", "failed", "cancelled"]

_TERMINAL_STEP_STATES = {"succeeded", "failed", "cancelled"}
_ALLOWED_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


class PlanRunError(RuntimeError):
    """Raised when a plan-run state transition violates the workflow contract."""


@dataclass(frozen=True, slots=True)
class PlanStepState:
    run_id: str
    step_id: str
    status: StepStatus


@dataclass(frozen=True, slots=True)
class PlanTransition:
    transition_id: int
    run_id: str
    step_id: str
    from_status: StepStatus
    to_status: StepStatus
    actor: str
    evidence_ids: tuple[str, ...]
    note: str | None
    transitioned_at: datetime


@dataclass(frozen=True, slots=True)
class PlanRun:
    run_id: str
    plan: TaskPlan
    status: RunStatus
    created_at: datetime
    steps: tuple[PlanStepState, ...]


class PlanRunStore:
    """Persist explicit plan state with atomic dependency checks and audit history."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_runs (
                    run_id TEXT PRIMARY KEY,
                    plan_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','completed','failed','cancelled')),
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_step_states (
                    run_id TEXT NOT NULL REFERENCES plan_runs(run_id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(
                        status IN ('pending','running','succeeded','failed','cancelled')
                    ),
                    PRIMARY KEY(run_id, step_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_transitions (
                    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    note TEXT,
                    transitioned_at TEXT NOT NULL,
                    FOREIGN KEY(run_id, step_id)
                        REFERENCES plan_step_states(run_id, step_id)
                )
                """
            )
            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS plan_transitions_no_update
                BEFORE UPDATE ON plan_transitions
                BEGIN
                    SELECT RAISE(ABORT, 'plan transition history is append-only');
                END
                """
            )
            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS plan_transitions_no_delete
                BEFORE DELETE ON plan_transitions
                BEGIN
                    SELECT RAISE(ABORT, 'plan transition history is append-only');
                END
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return current.astimezone(timezone.utc)

    def create(self, plan: TaskPlan, *, now: datetime | None = None) -> PlanRun:
        """Create a new run with all steps pending; plan IDs may be run more than once."""
        validate_plan(plan)
        current = self._now(now)
        run_id = str(uuid4())
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO plan_runs(run_id,plan_json,status,created_at) VALUES(?,?,?,?)",
                (run_id, plan.model_dump_json(), "active", current.isoformat()),
            )
            db.executemany(
                "INSERT INTO plan_step_states(run_id,step_id,status) VALUES(?,?,?)",
                [(run_id, step.step_id, "pending") for step in plan.steps],
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.get(run_id)

    def get(self, run_id: str) -> PlanRun:
        with self._connect() as db:
            row = db.execute(
                "SELECT plan_json,status,created_at FROM plan_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown plan run: {run_id}")
            steps = db.execute(
                "SELECT step_id,status FROM plan_step_states WHERE run_id=? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return PlanRun(
            run_id=run_id,
            plan=TaskPlan.model_validate_json(row[0]),
            status=row[1],
            created_at=datetime.fromisoformat(row[2]),
            steps=tuple(
                PlanStepState(run_id=run_id, step_id=step_id, status=status)
                for step_id, status in steps
            ),
        )

    def transitions(self, run_id: str) -> tuple[PlanTransition, ...]:
        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM plan_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(f"unknown plan run: {run_id}")
            rows = db.execute(
                """
                SELECT transition_id,step_id,from_status,to_status,actor,
                       evidence_json,note,transitioned_at
                FROM plan_transitions WHERE run_id=? ORDER BY transition_id
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            PlanTransition(
                transition_id=row[0],
                run_id=run_id,
                step_id=row[1],
                from_status=row[2],
                to_status=row[3],
                actor=row[4],
                evidence_ids=tuple(json.loads(row[5])),
                note=row[6],
                transitioned_at=datetime.fromisoformat(row[7]),
            )
            for row in rows
        )

    def transition(
        self,
        run_id: str,
        step_id: str,
        to_status: StepStatus,
        *,
        actor: str,
        evidence_ids: tuple[str, ...] = (),
        note: str | None = None,
        now: datetime | None = None,
    ) -> PlanRun:
        """Apply one audited state transition, atomically enforcing prerequisites."""
        cleaned_actor = actor.strip()
        if not 1 <= len(cleaned_actor) <= 80:
            raise ValueError("actor must be between 1 and 80 characters")
        if len(evidence_ids) > 32 or any(
            not item.strip() or len(item) > 160 for item in evidence_ids
        ):
            raise ValueError("evidence IDs must be 1-160 characters, with at most 32 entries")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence IDs cannot contain duplicates")
        if note is not None and len(note) > 300:
            raise ValueError("note cannot exceed 300 characters")
        current = self._now(now)

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT plan_json,status FROM plan_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown plan run: {run_id}")
            if run[1] != "active":
                raise PlanRunError(f"plan run is {run[1]} and cannot transition steps")

            plan = TaskPlan.model_validate_json(run[0])
            step_by_id = {step.step_id: step for step in plan.steps}
            if step_id not in step_by_id:
                raise KeyError(f"unknown step in plan run: {step_id}")

            state_row = db.execute(
                "SELECT status FROM plan_step_states WHERE run_id=? AND step_id=?",
                (run_id, step_id),
            ).fetchone()
            from_status = state_row[0]
            if to_status not in _ALLOWED_TRANSITIONS[from_status]:
                raise PlanRunError(
                    f"invalid step transition: {from_status} -> {to_status}"
                )

            if to_status == "running":
                for dependency in step_by_id[step_id].depends_on:
                    dependency_row = db.execute(
                        "SELECT status FROM plan_step_states WHERE run_id=? AND step_id=?",
                        (run_id, dependency),
                    ).fetchone()
                    if dependency_row[0] != "succeeded":
                        raise PlanRunError(
                            f"step {step_id!r} requires successful dependency {dependency!r}"
                        )

            if to_status in {"succeeded", "failed"} and not evidence_ids:
                raise PlanRunError(
                    f"{to_status} transitions require at least one evidence ID"
                )
            if to_status == "cancelled" and not (note and note.strip()):
                raise PlanRunError("cancelled transitions require a reason in note")

            db.execute(
                "UPDATE plan_step_states SET status=? WHERE run_id=? AND step_id=?",
                (to_status, run_id, step_id),
            )
            db.execute(
                """
                INSERT INTO plan_transitions(
                    run_id,step_id,from_status,to_status,actor,evidence_json,note,transitioned_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    step_id,
                    from_status,
                    to_status,
                    cleaned_actor,
                    json.dumps(evidence_ids),
                    note,
                    current.isoformat(),
                ),
            )
            statuses = [
                row[0]
                for row in db.execute(
                    "SELECT status FROM plan_step_states WHERE run_id=?", (run_id,)
                ).fetchall()
            ]
            if all(status in _TERMINAL_STEP_STATES for status in statuses):
                if "failed" in statuses:
                    run_status = "failed"
                elif "cancelled" in statuses:
                    run_status = "cancelled"
                else:
                    run_status = "completed"
                db.execute(
                    "UPDATE plan_runs SET status=? WHERE run_id=?",
                    (run_status, run_id),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.get(run_id)

    def cancel(
        self,
        run_id: str,
        *,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> PlanRun:
        """Cancel all unfinished steps, recording each cancellation atomically."""
        cleaned_actor = actor.strip()
        cleaned_reason = reason.strip()
        if not 1 <= len(cleaned_actor) <= 80:
            raise ValueError("actor must be between 1 and 80 characters")
        if not 1 <= len(cleaned_reason) <= 300:
            raise ValueError("cancellation reason must be between 1 and 300 characters")
        current = self._now(now)

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT status FROM plan_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown plan run: {run_id}")
            if run[0] != "active":
                raise PlanRunError(f"plan run is {run[0]} and cannot be cancelled")

            pending = db.execute(
                """
                SELECT step_id,status FROM plan_step_states
                WHERE run_id=? AND status IN ('pending','running')
                ORDER BY rowid
                """,
                (run_id,),
            ).fetchall()
            for step_id, from_status in pending:
                db.execute(
                    "UPDATE plan_step_states SET status='cancelled' "
                    "WHERE run_id=? AND step_id=?",
                    (run_id, step_id),
                )
                db.execute(
                    """
                    INSERT INTO plan_transitions(
                        run_id,step_id,from_status,to_status,actor,evidence_json,note,transitioned_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        step_id,
                        from_status,
                        "cancelled",
                        cleaned_actor,
                        "[]",
                        cleaned_reason,
                        current.isoformat(),
                    ),
                )
            db.execute(
                "UPDATE plan_runs SET status='cancelled' WHERE run_id=?", (run_id,)
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.get(run_id)
