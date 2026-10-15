"""Durable local SQLite event store with explicit retention controls."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from aie.contracts import AIEEvent


MAX_STATE_SNAPSHOT_BYTES = 16 * 1024 * 1024


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
            db.execute("""CREATE TABLE IF NOT EXISTS state_snapshots_v2 (
                snapshot_key TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                last_event_sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("""CREATE TABLE IF NOT EXISTS event_ingest_seq (
                ingest_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE)""")
            db.execute("""CREATE TABLE IF NOT EXISTS state_snapshot_integrity (
                snapshot_key TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute(
                """INSERT OR IGNORE INTO event_ingest_seq(event_id)
                   SELECT event_id FROM events ORDER BY rowid ASC"""
            )

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
        inserted = 0
        with self._connect() as db:
            for record in records:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO events(event_id,timestamp,source,event_type,payload) "
                    "VALUES(?,?,?,?,?)",
                    record,
                )
                if cursor.rowcount == 1:
                    db.execute(
                        "INSERT INTO event_ingest_seq(event_id) VALUES(?)",
                        (record[0],),
                    )
                    inserted += 1
        return inserted

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


    def events_after_sequence(
        self, after_sequence: int = 0, *, limit: int = 10000
    ) -> list[tuple[int, AIEEvent]]:
        """Read events in durable SQLite ingestion order, including late imports."""
        if isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("after_sequence must be zero or greater")
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT seq.ingest_seq, events.payload FROM events
                   JOIN event_ingest_seq AS seq ON seq.event_id = events.event_id
                   WHERE seq.ingest_seq > ? ORDER BY seq.ingest_seq ASC LIMIT ?""",
                (after_sequence, limit),
            ).fetchall()
        return [
            (int(row[0]), AIEEvent.model_validate(json.loads(row[1])))
            for row in rows
        ]

    def save_state_snapshot(
        self, key: str, last_event_sequence: int, payload: str, *, schema_version: int = 1
    ) -> None:
        """Atomically persist a versioned projection and its ingestion watermark."""
        if not key or len(key) > 128:
            raise ValueError("snapshot key must contain 1..128 characters")
        if isinstance(last_event_sequence, bool) or last_event_sequence < 0:
            raise ValueError("last_event_sequence must be zero or greater")
        if not isinstance(payload, str):
            raise ValueError("snapshot payload must be a string")
        payload_size = len(payload.encode("utf-8"))
        if payload_size > MAX_STATE_SNAPSHOT_BYTES:
            raise ValueError(
                f"snapshot is {payload_size} bytes; limit is {MAX_STATE_SNAPSHOT_BYTES}. "
                "The previous snapshot was left unchanged."
            )
        if not 1 <= schema_version <= 1000:
            raise ValueError("schema_version must be between 1 and 1000")
        with self._connect() as db:
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            db.execute(
                """INSERT INTO state_snapshots_v2(
                    snapshot_key, schema_version, last_event_sequence, payload, updated_at
                ) VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(snapshot_key) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    last_event_sequence=excluded.last_event_sequence,
                    payload=excluded.payload,
                    updated_at=CURRENT_TIMESTAMP""",
                (key, schema_version, last_event_sequence, payload),
            )
            db.execute(
                """INSERT INTO state_snapshot_integrity(snapshot_key, payload_sha256, updated_at)
                   VALUES(?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(snapshot_key) DO UPDATE SET
                   payload_sha256=excluded.payload_sha256, updated_at=CURRENT_TIMESTAMP""",
                (key, digest),
            )

    def load_state_snapshot(self, key: str) -> tuple[int, int, str] | None:
        """Return (schema version, ingestion watermark, JSON payload)."""
        if not key or len(key) > 128:
            raise ValueError("snapshot key must contain 1..128 characters")
        with self._connect() as db:
            row = db.execute(
                """SELECT snapshot.schema_version, snapshot.last_event_sequence,
                          snapshot.payload, integrity.payload_sha256
                   FROM state_snapshots_v2 AS snapshot
                   LEFT JOIN state_snapshot_integrity AS integrity
                     ON integrity.snapshot_key = snapshot.snapshot_key
                   WHERE snapshot.snapshot_key = ?""",
                (key,),
            ).fetchone()
        if row is None:
            return None
        payload = str(row[2])
        if row[3] is not None:
            actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if actual != row[3]:
                raise ValueError(
                    f"snapshot '{key}' failed SHA-256 integrity verification; "
                    "use --rebuild if retained events are sufficient"
                )
        return int(row[0]), int(row[1]), payload

    def delete_state_snapshot(self, key: str) -> None:
        if not key or len(key) > 128:
            raise ValueError("snapshot key must contain 1..128 characters")
        with self._connect() as db:
            db.execute("DELETE FROM state_snapshots_v2 WHERE snapshot_key = ?", (key,))
            db.execute("DELETE FROM state_snapshot_integrity WHERE snapshot_key = ?", (key,))

    def recent(self, limit: int = 50) -> list[AIEEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT payload FROM events
                   ORDER BY julianday(timestamp) DESC, event_id DESC LIMIT ?""",
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
                deleted = db.execute(
                    "DELETE FROM events WHERE julianday(timestamp) < julianday(?)",
                    (cutoff,),
                ).rowcount
                db.execute(
                    "DELETE FROM event_ingest_seq WHERE event_id NOT IN (SELECT event_id FROM events)"
                )
                return deleted

        if keep_latest is None or keep_latest < 0:
            raise ValueError("keep_latest must be zero or greater")
        with self._connect() as db:
            deleted = db.execute(
                """DELETE FROM events
                   WHERE event_id NOT IN (
                       SELECT event_id FROM events
                       ORDER BY julianday(timestamp) DESC, event_id DESC LIMIT ?
                   )""",
                (keep_latest,),
            ).rowcount
            db.execute(
                "DELETE FROM event_ingest_seq WHERE event_id NOT IN (SELECT event_id FROM events)"
            )
            return deleted
