"""Durable local SQLite event store."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

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
            db.execute("CREATE INDEX IF NOT EXISTS idx_events_type_timestamp ON events(event_type, timestamp)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_events_source_timestamp ON events(source, timestamp)")

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

    def get(self, event_id: str) -> AIEEvent | None:
        """Fetch one event by stable ID."""
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return AIEEvent.model_validate(json.loads(row[0]))

    def recent(self, limit: int = 50) -> list[AIEEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [AIEEvent.model_validate(json.loads(row[0])) for row in rows]

    def query_events(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        event_types: Iterable[str] = (),
        sources: Iterable[str] = (),
        limit: int = 1000,
    ) -> list[AIEEvent]:
        """Query normalized evidence by UTC time window, type and source.

        The query returns newest events first. Filters are parameterized and indexed;
        callers should build privacy-safe summaries instead of exposing raw payloads.
        """
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        if since is not None and since.tzinfo is None:
            raise ValueError("since must be timezone-aware")
        if until is not None and until.tzinfo is None:
            raise ValueError("until must be timezone-aware")
        if since is not None and until is not None and since > until:
            raise ValueError("since must not be later than until")

        clauses: list[str] = []
        parameters: list[object] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            parameters.append(since.astimezone(timezone.utc).isoformat())
        if until is not None:
            clauses.append("timestamp <= ?")
            parameters.append(until.astimezone(timezone.utc).isoformat())

        normalized_types = tuple(dict.fromkeys(event_types))
        normalized_sources = tuple(dict.fromkeys(sources))
        if any(not isinstance(value, str) or not value.strip() for value in normalized_types):
            raise ValueError("event_types must contain non-empty strings")
        if any(not isinstance(value, str) or not value.strip() for value in normalized_sources):
            raise ValueError("sources must contain non-empty strings")

        if normalized_types:
            placeholders = ",".join("?" for _ in normalized_types)
            clauses.append(f"event_type IN ({placeholders})")
            parameters.extend(normalized_types)
        if normalized_sources:
            placeholders = ",".join("?" for _ in normalized_sources)
            clauses.append(f"source IN ({placeholders})")
            parameters.extend(normalized_sources)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM events" + where
                + " ORDER BY timestamp DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [AIEEvent.model_validate(json.loads(row[0])) for row in rows]

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def count_before(self, cutoff: datetime) -> int:
        """Count events older than an aware UTC cutoff without deleting them."""
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp < ?",
                (cutoff.isoformat(),),
            ).fetchone()
        return int(row[0])

    def delete_before(self, cutoff: datetime) -> int:
        """Delete events older than an aware UTC cutoff; newer events are untouched."""
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM events WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            return int(cursor.rowcount)
