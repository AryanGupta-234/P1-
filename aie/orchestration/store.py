"""SQLite-backed task-run state with explicit, transactional transitions."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aie.orchestration.models import AgentRun, RunStatus, StepStatus, TaskStepRecord
from aie.planning.models import PlanStep, TaskPlan
from aie.planning.validator import next_ready_steps, validate_plan


_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


class TaskRunStore:
    """Persist plans, step outcomes and lifecycle events in a local SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    plan_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'ready','running','waiting_approval','blocked',
                        'completed','failed','cancelled'
                    )),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_run_steps (
                    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending','running','waiting_approval','authorized',
                        'completed','failed','blocked','cancelled'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    summary TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    proposal_id TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    PRIMARY KEY(run_id, step_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_updated
                    ON agent_runs(updated_at);
                CREATE INDEX IF NOT EXISTS idx_agent_run_steps_status
                    ON agent_run_steps(run_id, status);
                CREATE TABLE IF NOT EXISTS agent_run_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                    step_id TEXT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_run_events_run
                    ON agent_run_events(run_id, sequence);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        run_id: str,
        event_type: str,
        *,
        step_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        db.execute(
            """INSERT INTO agent_run_events(run_id,step_id,event_type,timestamp,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                run_id,
                step_id,
                event_type,
                TaskRunStore._now().isoformat(),
                json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=True),
            ),
        )

    def create(self, plan: TaskPlan, *, run_id: str | None = None) -> AgentRun:
        validate_plan(plan)
        identifier = run_id or str(uuid4())
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT INTO agent_runs
                    (run_id,plan_json,status,created_at,updated_at,cancel_requested,error)
                    VALUES(?,?,'ready',?,?,0,NULL)""",
                    (identifier, plan.model_dump_json(), now, now),
                )
                db.executemany(
                    """INSERT INTO agent_run_steps(run_id,step_id,status)
                    VALUES(?,?,'pending')""",
                    [(identifier, step.step_id) for step in plan.steps],
                )
                self._event(
                    db, identifier, "run.created",
                    payload={"plan_id": plan.plan_id, "step_count": len(plan.steps)},
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(identifier)  # type: ignore[return-value]

    @staticmethod
    def _step(row: sqlite3.Row) -> TaskStepRecord:
        return TaskStepRecord(
            step_id=row["step_id"],
            status=row["status"],
            attempts=row["attempts"],
            summary=row["summary"],
            evidence_ids=tuple(json.loads(row["evidence_json"] or "[]")),
            proposal_id=row["proposal_id"],
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            error=row["error"],
        )

    def get(self, run_id: str) -> AgentRun | None:
        with self._connect() as db:
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                return None
            steps = db.execute(
                "SELECT * FROM agent_run_steps WHERE run_id=? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return AgentRun(
            run_id=run["run_id"],
            plan=TaskPlan.model_validate_json(run["plan_json"]),
            status=run["status"],
            created_at=datetime.fromisoformat(run["created_at"]),
            updated_at=datetime.fromisoformat(run["updated_at"]),
            steps=tuple(self._step(row) for row in steps),
            cancel_requested=bool(run["cancel_requested"]),
            error=run["error"],
        )

    def list(self, *, limit: int = 50) -> list[AgentRun]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._connect() as db:
            rows = db.execute(
                "SELECT run_id FROM agent_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [item for row in rows if (item := self.get(row["run_id"])) is not None]

    def claim_next_ready(self, run_id: str) -> tuple[str, PlanStep] | None:
        """Atomically claim one dependency-ready step; never claims action authority."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                run = db.execute(
                    "SELECT plan_json,status,cancel_requested FROM agent_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if run is None:
                    raise ValueError("task run was not found")
                if run["cancel_requested"]:
                    db.execute(
                        "UPDATE agent_runs SET status='cancelled',updated_at=? WHERE run_id=?",
                        (self._now().isoformat(), run_id),
                    )
                    db.execute(
                        "UPDATE agent_run_steps SET status='cancelled',completed_at=? "
                        "WHERE run_id=? AND status='pending'",
                        (self._now().isoformat(), run_id),
                    )
                    self._event(db, run_id, "run.cancelled")
                    db.execute("COMMIT")
                    return None
                if run["status"] in _TERMINAL_RUN_STATUSES | {"waiting_approval", "blocked"}:
                    db.execute("COMMIT")
                    return None

                plan = TaskPlan.model_validate_json(run["plan_json"])
                rows = db.execute(
                    "SELECT step_id,status FROM agent_run_steps WHERE run_id=?",
                    (run_id,),
                ).fetchall()
                statuses = {row["step_id"]: row["status"] for row in rows}
                completed = {step_id for step_id, status in statuses.items() if status == "completed"}
                ready = next_ready_steps(plan, completed_step_ids=completed)
                if not ready:
                    if all(status == "completed" for status in statuses.values()):
                        db.execute(
                            "UPDATE agent_runs SET status='completed',updated_at=? WHERE run_id=?",
                            (self._now().isoformat(), run_id),
                        )
                        self._event(db, run_id, "run.completed")
                    db.execute("COMMIT")
                    return None

                step = ready[0]
                if statuses.get(step.step_id) != "pending":
                    db.execute("COMMIT")
                    return None
                now = self._now().isoformat()
                changed = db.execute(
                    """UPDATE agent_run_steps
                    SET status='running', attempts=attempts+1, started_at=?, completed_at=NULL,
                        error=NULL
                    WHERE run_id=? AND step_id=? AND status='pending'""",
                    (now, run_id, step.step_id),
                ).rowcount
                if changed != 1:
                    db.execute("ROLLBACK")
                    return None
                db.execute(
                    "UPDATE agent_runs SET status='running',updated_at=?,error=NULL WHERE run_id=?",
                    (now, run_id),
                )
                self._event(db, run_id, "step.started", step_id=step.step_id)
                db.execute("COMMIT")
                return step.step_id, step
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def finish_step(
        self,
        run_id: str,
        step_id: str,
        *,
        success: bool,
        summary: str,
        evidence_ids: tuple[str, ...] = (),
    ) -> AgentRun:
        if not 1 <= len(summary.strip()) <= 500:
            raise ValueError("step summary must contain 1-500 non-whitespace characters")
        if len(evidence_ids) > 20 or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence IDs must be unique and limited to 20")
        if any(not isinstance(item, str) or not 1 <= len(item) <= 120 for item in evidence_ids):
            raise ValueError("invalid evidence ID")
        status: StepStatus = "completed" if success else "failed"
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status FROM agent_run_steps WHERE run_id=? AND step_id=?",
                    (run_id, step_id),
                ).fetchone()
                if row is None:
                    raise ValueError("task step was not found")
                if row["status"] != "running":
                    raise ValueError("task step is not currently running")
                db.execute(
                    """UPDATE agent_run_steps SET status=?,summary=?,evidence_json=?,
                        completed_at=?,error=? WHERE run_id=? AND step_id=?""",
                    (
                        status, summary, json.dumps(list(evidence_ids)),
                        now, None if success else summary, run_id, step_id,
                    ),
                )
                statuses = [
                    item["status"] for item in db.execute(
                        "SELECT status FROM agent_run_steps WHERE run_id=?",
                        (run_id,),
                    ).fetchall()
                ]
                run_status: RunStatus = (
                    "failed" if not success
                    else "completed" if all(item == "completed" for item in statuses)
                    else "ready"
                )
                db.execute(
                    "UPDATE agent_runs SET status=?,updated_at=?,error=? WHERE run_id=?",
                    (run_status, now, None if success else summary, run_id),
                )
                self._event(
                    db, run_id, "step.completed" if success else "step.failed",
                    step_id=step_id,
                    payload={"evidence_count": len(evidence_ids)},
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(run_id)  # type: ignore[return-value]

    def wait_for_approval(self, run_id: str, step_id: str, proposal_id: str) -> AgentRun:
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status FROM agent_run_steps WHERE run_id=? AND step_id=?",
                    (run_id, step_id),
                ).fetchone()
                if row is None or row["status"] != "running":
                    raise ValueError("action step is not currently running")
                db.execute(
                    """UPDATE agent_run_steps SET status='waiting_approval',proposal_id=?
                    WHERE run_id=? AND step_id=?""",
                    (proposal_id, run_id, step_id),
                )
                db.execute(
                    "UPDATE agent_runs SET status='waiting_approval',updated_at=? WHERE run_id=?",
                    (now, run_id),
                )
                self._event(
                    db, run_id, "action.awaiting_approval", step_id=step_id,
                    payload={"proposal_id": proposal_id},
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(run_id)  # type: ignore[return-value]

    def resolve_action_review(
        self,
        run_id: str,
        step_id: str,
        *,
        outcome: str,
        reason: str,
    ) -> AgentRun:
        """Reflect review, but never mark an approved action as executed."""
        if outcome not in {"approved", "rejected", "blocked"}:
            raise ValueError("invalid action review outcome")
        now = self._now().isoformat()
        step_status: StepStatus = "authorized" if outcome == "approved" else (
            "failed" if outcome == "rejected" else "blocked"
        )
        run_status: RunStatus = "blocked" if outcome in {"approved", "blocked"} else "failed"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status FROM agent_run_steps WHERE run_id=? AND step_id=?",
                    (run_id, step_id),
                ).fetchone()
                if row is None or row["status"] != "waiting_approval":
                    raise ValueError("task step is not awaiting action approval")
                db.execute(
                    """UPDATE agent_run_steps SET status=?,error=?,completed_at=?
                    WHERE run_id=? AND step_id=?""",
                    (step_status, reason[:500], now, run_id, step_id),
                )
                db.execute(
                    "UPDATE agent_runs SET status=?,updated_at=?,error=? WHERE run_id=?",
                    (run_status, now, reason[:500], run_id),
                )
                self._event(
                    db, run_id, "action.review_" + outcome, step_id=step_id,
                    payload={"reason": reason[:500], "executed": False},
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(run_id)  # type: ignore[return-value]

    def request_cancel(self, run_id: str) -> AgentRun:
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT status FROM agent_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("task run was not found")
                if row["status"] in _TERMINAL_RUN_STATUSES:
                    db.execute("COMMIT")
                    return self.get(run_id)  # type: ignore[return-value]
                if row["status"] == "running":
                    db.execute(
                        "UPDATE agent_runs SET cancel_requested=1,updated_at=? WHERE run_id=?",
                        (now, run_id),
                    )
                    self._event(db, run_id, "run.cancel_requested")
                else:
                    db.execute(
                        "UPDATE agent_runs SET status='cancelled',updated_at=? WHERE run_id=?",
                        (now, run_id),
                    )
                    db.execute(
                        """UPDATE agent_run_steps SET status='cancelled',completed_at=?
                        WHERE run_id=? AND status IN ('pending','waiting_approval','authorized')""",
                        (now, run_id),
                    )
                    self._event(db, run_id, "run.cancelled")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(run_id)  # type: ignore[return-value]

    def recover_interrupted(self) -> int:
        """Fail closed on process-restart ambiguity; never replay an in-flight step."""
        now = self._now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    "SELECT run_id,step_id FROM agent_run_steps WHERE status='running'"
                ).fetchall()
                for row in rows:
                    reason = (
                        "Process restarted while this step was running. Inspect external "
                        "state before starting a new task; automatic replay is disabled."
                    )
                    db.execute(
                        """UPDATE agent_run_steps SET status='failed',error=?,completed_at=?
                        WHERE run_id=? AND step_id=?""",
                        (reason, now, row["run_id"], row["step_id"]),
                    )
                    db.execute(
                        "UPDATE agent_runs SET status='failed',updated_at=?,error=? WHERE run_id=?",
                        (now, reason, row["run_id"]),
                    )
                    self._event(
                        db, row["run_id"], "step.interrupted", step_id=row["step_id"],
                        payload={"automatic_replay": False},
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return len(rows)
