"""Durable local SQLite event store with explicit retention controls."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from aie.contracts import AIEEvent


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
                source TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            db.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_key TEXT PRIMARY KEY, checkpoint_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def append(self, event: AIEEvent) -> bool:
        return self.append_many([event]) == 1

    def append_many(self, events: Iterable[AIEEvent]) -> int:
        """Insert a batch in one transaction; duplicate event IDs are ignored."""
        records = [
            (event.event_id, event.timestamp.isoformat(), event.source,
             event.event_type, event.model_dump_json())
            for event in events
        ]
        if not records:
            return 0
        with self._connect() as db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO events(event_id,timestamp,source,event_type,payload) "
                "VALUES(?,?,?,?,?)",
                records,
            )
            return db.total_changes - before

    def get_checkpoint(self, key: str) -> str | None:
        """Read a small durable collector checkpoint by its namespaced key."""
        if not key or len(key) > 128:
            raise ValueError("checkpoint key must contain 1..128 characters")
        with self._connect() as db:
            row = db.execute(
                "SELECT checkpoint_value FROM checkpoints WHERE checkpoint_key = ?",
                (key,),
            ).fetchone()
        return str(row[0]) if row else None

    def set_checkpoint(self, key: str, value: str) -> None:
        """Atomically upsert a collector checkpoint; callers control commit timing."""
        if not key or len(key) > 128:
            raise ValueError("checkpoint key must contain 1..128 characters")
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("checkpoint value must be a string of at most 4096 characters")
        with self._connect() as db:
            db.execute(
                """INSERT INTO checkpoints(checkpoint_key, checkpoint_value, updated_at)
                   VALUES(?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(checkpoint_key) DO UPDATE SET
                   checkpoint_value=excluded.checkpoint_value,
                   updated_at=CURRENT_TIMESTAMP""",
                (key, value),
            )

    def recent(self, limit: int = 50) -> list[AIEEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM events ORDER BY julianday(timestamp) DESC, event_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AIEEvent.model_validate(json.loads(row[0])) for row in rows]

    def events_since(self, since: datetime, *, limit: int = 10000) -> list[AIEEvent]:
        """Read a bounded chronological window for offline correlation and analysis."""
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("since must be timezone-aware")
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT payload FROM events
                   WHERE julianday(timestamp) >= julianday(?)
                   ORDER BY julianday(timestamp) ASC, event_id ASC LIMIT ?""",
                (since.isoformat(), limit),
            ).fetchall()
        return [AIEEvent.model_validate(json.loads(row[0])) for row in rows]

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def export_jsonl(self, destination: Path) -> int:
        """Export all stored event payloads in chronological order as JSONL."""
        if destination.resolve() == self.path.resolve():
            raise ValueError("export destination must not be the SQLite database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM events ORDER BY julianday(timestamp) ASC, event_id ASC"
            ).fetchall()
        destination.write_text("".join(row[0] + "\n" for row in rows), encoding="utf-8")
        return len(rows)

    def prune(
        self,
        *,
        older_than: datetime | None = None,
        keep_latest: int | None = None,
    ) -> int:
        """Delete old events or cap the store, requiring exactly one explicit policy."""
        if (older_than is None) == (keep_latest is None):
            raise ValueError("provide exactly one of older_than or keep_latest")
        if older_than is not None:
            if older_than.tzinfo is None or older_than.utcoffset() is None:
                raise ValueError("older_than must be timezone-aware")
            cutoff = older_than.isoformat()
            with self._connect() as db:
                before = db.total_changes
                db.execute(
                    "DELETE FROM events WHERE julianday(timestamp) < julianday(?)",
                    (cutoff,),
                )
                return db.total_changes - before

        if keep_latest is None or keep_latest < 0:
            raise ValueError("keep_latest must be zero or greater")
        with self._connect() as db:
            before = db.total_changes
            db.execute(
                """DELETE FROM events
                   WHERE event_id NOT IN (
                       SELECT event_id FROM events
                       ORDER BY julianday(timestamp) DESC, event_id DESC LIMIT ?
                   )""",
                (keep_latest,),
            )
            return db.total_changes - before
