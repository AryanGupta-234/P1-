"""Transactional local persistence and event journal for orchestration runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aie.orchestration.models import TaskRun


class TaskRunConflict(RuntimeError):
    """Raised when another writer changed a run after it was read."""


class TaskRunStore:
    """SQLite task-run store with compare-and-swap writes and append-only events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS task_runs (
                    run_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS task_run_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES task_runs(run_id)
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_runs_status_updated "
                "ON task_runs(status, updated_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_run_events_run "
                "ON task_run_events(run_id, sequence)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _append_event(
        db: sqlite3.Connection,
        *,
        run_id: str,
        event_type: str,
        timestamp: datetime,
        version: int,
        payload: dict[str, Any],
    ) -> None:
        db.execute(
            """INSERT INTO task_run_events
            (event_id, run_id, event_type, timestamp, version, payload)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                run_id,
                event_type,
                timestamp.astimezone(timezone.utc).isoformat(),
                version,
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            ),
        )

    def create(self, run: TaskRun) -> TaskRun:
        now = datetime.now(timezone.utc)
        state = run.model_copy(update={"updated_at": now, "version": 1})
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT INTO task_runs
                    (run_id, state_json, status, version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        state.run_id,
                        state.model_dump_json(),
                        state.status,
                        state.version,
                        state.created_at.astimezone(timezone.utc).isoformat(),
                        now.isoformat(),
                    ),
                )
                self._append_event(
                    db,
                    run_id=state.run_id,
                    event_type="task.created",
                    timestamp=now,
                    version=state.version,
                    payload={"plan_id": state.plan.plan_id, "step_count": len(state.steps)},
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return state

    def get(self, run_id: str) -> TaskRun | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT state_json FROM task_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return TaskRun.model_validate_json(row[0]) if row else None

    def save(
        self,
        run: TaskRun,
        *,
        expected_version: int,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> TaskRun:
        if run.version != expected_version:
            raise ValueError("run.version must equal expected_version")
        now = datetime.now(timezone.utc)
        updated = run.model_copy(
            update={"version": expected_version + 1, "updated_at": now}
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cursor = db.execute(
                    """UPDATE task_runs
                    SET state_json = ?, status = ?, version = ?, updated_at = ?
                    WHERE run_id = ? AND version = ?""",
                    (
                        updated.model_dump_json(),
                        updated.status,
                        updated.version,
                        now.isoformat(),
                        updated.run_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise TaskRunConflict(
                        "task run changed or disappeared; reload before retrying"
                    )
                self._append_event(
                    db,
                    run_id=updated.run_id,
                    event_type=event_type,
                    timestamp=now,
                    version=updated.version,
                    payload=details or {},
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return updated

    def list(self, *, limit: int = 100) -> list[TaskRun]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                "SELECT state_json FROM task_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [TaskRun.model_validate_json(row[0]) for row in rows]

    def events(self, run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT sequence, event_type, timestamp, version, payload
                FROM task_run_events WHERE run_id = ?
                ORDER BY sequence ASC LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return [
            {
                "sequence": row[0],
                "event_type": row[1],
                "timestamp": row[2],
                "version": row[3],
                "payload": json.loads(row[4]),
            }
            for row in rows
        ]
