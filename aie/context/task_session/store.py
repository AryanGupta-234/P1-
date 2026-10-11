"""SQLite persistence for explicit user-controlled task sessions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aie.context.task_session.models import TaskSession, new_task_session


class TaskSessionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS task_sessions (
                    session_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('active','ended'))
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_sessions_started "
                "ON task_sessions(started_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _row_to_model(row) -> TaskSession:
        return TaskSession(
            session_id=row[0],
            label=row[1],
            started_at=datetime.fromisoformat(row[2]),
            ended_at=datetime.fromisoformat(row[3]) if row[3] else None,
            status=row[4],
        )

    def start(self, label: str, *, now: datetime | None = None) -> TaskSession:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        session = new_task_session(label, now=current)
        with self._connect() as db:
            db.execute(
                "UPDATE task_sessions SET ended_at = ?, status = 'ended' "
                "WHERE status = 'active'",
                (current.isoformat(),),
            )
            db.execute(
                "INSERT INTO task_sessions(session_id,label,started_at,ended_at,status) "
                "VALUES(?,?,?,?,?)",
                (
                    session.session_id,
                    session.label,
                    session.started_at.isoformat(),
                    None,
                    session.status,
                ),
            )
        return session

    def current(self) -> TaskSession | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT session_id,label,started_at,ended_at,status "
                "FROM task_sessions WHERE status = 'active' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return self._row_to_model(row) if row else None

    def end(self, *, now: datetime | None = None) -> TaskSession | None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._connect() as db:
            row = db.execute(
                "SELECT session_id,label,started_at,ended_at,status "
                "FROM task_sessions WHERE status = 'active' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE task_sessions SET ended_at = ?, status = 'ended' "
                "WHERE session_id = ?",
                (current.isoformat(), row[0]),
            )
            ended = (row[0], row[1], row[2], current.isoformat(), "ended")
        return self._row_to_model(ended)

    def list(self, *, limit: int = 50) -> list[TaskSession]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._connect() as db:
            rows = db.execute(
                "SELECT session_id,label,started_at,ended_at,status "
                "FROM task_sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_model(row) for row in rows]
