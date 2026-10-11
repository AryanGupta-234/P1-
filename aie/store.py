"""Durable local SQLite event store."""
from __future__ import annotations

import json
import sqlite3
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

    def recent(self, limit: int = 50) -> list[AIEEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [AIEEvent.model_validate(json.loads(row[0])) for row in rows]

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
