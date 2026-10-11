"""SQLite-backed personal memory with explicit capture and local retrieval."""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aie.memory.models import MemoryKind, MemoryRecord, MemorySearchHit
from aie.store import EventStore

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]{1,39}")


@dataclass(frozen=True, slots=True)
class StoredMemory:
    memory: MemoryRecord
    status: str


class MemoryStore:
    """User-controlled memory database with TTL, provenance and correction history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    payload TEXT NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_status_kind ON memories(status, kind)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_expiry ON memories(expires_at)"
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (memory_id, model)
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model ON memory_embeddings(model)"
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS memory_lineage (
                    memory_id TEXT NOT NULL,
                    source_memory_id TEXT NOT NULL,
                    relation TEXT NOT NULL CHECK(relation IN ('merged_from')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(memory_id, source_memory_id)
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_lineage_source ON memory_lineage(source_memory_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None:
            raise ValueError(f"{field} must be timezone-aware")
        return value.astimezone(timezone.utc)

    def save(
        self,
        memory: MemoryRecord,
        *,
        event_store: EventStore | None = None,
        task_run_store=None,
    ) -> MemoryRecord:
        """Insert a memory and atomically supersede a prior version if requested."""
        if memory.source_event_ids:
            if event_store is None:
                raise ValueError("event_store is required when memory provenance IDs are supplied")
            missing = [
                event_id for event_id in memory.source_event_ids
                if event_store.get(event_id) is None
            ]
            if missing:
                raise ValueError(f"source event not found: {missing[0]}")

        if memory.source_task_run_ids:
            if task_run_store is None or not callable(getattr(task_run_store, "get", None)):
                raise ValueError("task_run_store is required when memory task-run provenance IDs are supplied")
            for run_id in memory.source_task_run_ids:
                source_run = task_run_store.get(run_id)
                if source_run is None or source_run.status != "completed":
                    raise ValueError("source task run must exist and be completed")

        now = datetime.now(timezone.utc)
        normalized = memory.model_copy(
            update={
                "created_at": self._aware_utc(memory.created_at, "created_at"),
                "updated_at": now,
                "expires_at": (
                    self._aware_utc(memory.expires_at, "expires_at")
                    if memory.expires_at is not None
                    else None
                ),
            }
        )
        with self._connect() as db:
            if normalized.supersedes_id:
                previous = db.execute(
                    "SELECT status, kind FROM memories WHERE memory_id = ?",
                    (normalized.supersedes_id,),
                ).fetchone()
                if previous is None:
                    raise ValueError("memory to supersede was not found")
                if previous[0] != "active":
                    raise ValueError("only an active memory can be superseded")
                if previous[1] != normalized.kind:
                    raise ValueError("a correction must keep the original memory kind")
                db.execute(
                    "UPDATE memories SET status = 'superseded' WHERE memory_id = ?",
                    (normalized.supersedes_id,),
                )
                db.execute(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?",
                    (normalized.supersedes_id,),
                )
            db.execute(
                """INSERT INTO memories
                (memory_id, kind, sensitivity, status, created_at, expires_at, payload)
                VALUES (?, ?, ?, 'active', ?, ?, ?)""",
                (
                    normalized.memory_id,
                    normalized.kind,
                    normalized.sensitivity,
                    normalized.created_at.isoformat(),
                    normalized.expires_at.isoformat() if normalized.expires_at else None,
                    normalized.model_dump_json(),
                ),
            )
        return normalized

    def get(self, memory_id: str, *, include_superseded: bool = False) -> StoredMemory | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT status, payload FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None or (row[0] != "active" and not include_superseded):
            return None
        return StoredMemory(memory=MemoryRecord.model_validate_json(row[1]), status=row[0])

    def list_memories(
        self,
        *,
        kind: MemoryKind | None = None,
        include_sensitive: bool = False,
        include_superseded: bool = False,
        include_expired: bool = False,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[StoredMemory]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        current = self._aware_utc(now or datetime.now(timezone.utc), "now")
        clauses: list[str] = []
        parameters: list[object] = []
        if not include_superseded:
            clauses.append("status = 'active'")
        if not include_sensitive:
            clauses.append("sensitivity != 'sensitive'")
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind)
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            parameters.append(current.isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, payload FROM memories" + where
                + " ORDER BY created_at DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [
            StoredMemory(memory=MemoryRecord.model_validate_json(row[1]), status=row[0])
            for row in rows
        ]

    def search(
        self,
        query: str,
        *,
        kind: MemoryKind | None = None,
        include_sensitive: bool = False,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[MemorySearchHit]:
        """Rank local memories by deterministic token/tag overlap (not embeddings)."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(query, str) or len(query) > 500:
            raise ValueError("query must be a string of at most 500 characters")
        query_tokens = set(_TOKEN.findall(query.lower()))
        if not query_tokens:
            return []
        records = self.list_memories(
            kind=kind,
            include_sensitive=include_sensitive,
            limit=1000,
            now=now,
        )
        hits: list[MemorySearchHit] = []
        for item in records:
            memory = item.memory
            content_tokens = set(_TOKEN.findall(memory.content.lower()))
            tag_tokens = set(_TOKEN.findall(" ".join(memory.tags).lower()))
            content_match = len(query_tokens & content_tokens) / len(query_tokens)
            tag_match = len(query_tokens & tag_tokens) / len(query_tokens)
            phrase_bonus = 0.5 if query.strip().lower() in memory.content.lower() else 0.0
            score = min(2.0, content_match + (0.5 * tag_match) + phrase_bonus)
            if score > 0:
                hits.append(MemorySearchHit(memory=memory, score=score))
        hits.sort(key=lambda hit: (hit.score, hit.memory.updated_at), reverse=True)
        return hits[:limit]

    def has_embedding(self, memory_id: str, model: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM memory_embeddings WHERE memory_id = ? AND model = ?",
                (memory_id, model),
            ).fetchone()
        return row is not None

    def save_embedding(
        self,
        memory_id: str,
        model: str,
        vector: list[float],
    ) -> None:
        """Store one local embedding for an active memory/model pair."""
        if not isinstance(model, str) or not model.strip() or len(model) > 120:
            raise ValueError("embedding model must be a non-empty name up to 120 characters")
        memory = self.get(memory_id)
        if memory is None:
            raise ValueError("only active memories can be embedded")
        if not isinstance(vector, list) or not 1 <= len(vector) <= 4096:
            raise ValueError("embedding vectors must contain between 1 and 4096 values")
        normalized: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("embedding values must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("embedding values must be finite")
            normalized.append(number)
        if math.sqrt(sum(value * value for value in normalized)) <= 1e-12:
            raise ValueError("embedding vector cannot be zero")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """INSERT INTO memory_embeddings
                (memory_id, model, dimensions, vector_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_id, model) DO UPDATE SET
                    dimensions = excluded.dimensions,
                    vector_json = excluded.vector_json,
                    updated_at = excluded.updated_at""",
                (
                    memory_id,
                    model,
                    len(normalized),
                    json.dumps(normalized, separators=(",", ":"), allow_nan=False),
                    now,
                ),
            )

    def search_semantic(
        self,
        vector: list[float],
        *,
        model: str,
        kind: MemoryKind | None = None,
        include_sensitive: bool = False,
        limit: int = 10,
        minimum_score: float = 0.05,
        now: datetime | None = None,
    ) -> list[MemorySearchHit]:
        """Search local vectors; ignore unrelated records below cosine-similarity threshold."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if isinstance(minimum_score, bool) or not isinstance(minimum_score, (int, float)):
            raise ValueError("minimum_score must be numeric between 0 and 1")
        if not 0.0 <= float(minimum_score) <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("embedding model is required")
        if not isinstance(vector, list) or not 1 <= len(vector) <= 4096:
            raise ValueError("query vector must contain between 1 and 4096 values")
        query: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("query embedding values must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("query embedding values must be finite")
            query.append(number)
        query_norm = math.sqrt(sum(value * value for value in query))
        if query_norm <= 1e-12:
            raise ValueError("query embedding cannot be zero")

        eligible = self.list_memories(
            kind=kind,
            include_sensitive=include_sensitive,
            limit=1000,
            now=now,
        )
        records = {item.memory.memory_id: item.memory for item in eligible}
        if not records:
            return []
        placeholders = ",".join("?" for _ in records)
        parameters: list[object] = [model, *records.keys()]
        with self._connect() as db:
            rows = db.execute(
                "SELECT memory_id, dimensions, vector_json FROM memory_embeddings "
                f"WHERE model = ? AND memory_id IN ({placeholders})",
                parameters,
            ).fetchall()

        hits: list[MemorySearchHit] = []
        for memory_id, dimensions, raw_vector in rows:
            if dimensions != len(query):
                continue
            try:
                stored = json.loads(raw_vector)
                if (
                    not isinstance(stored, list)
                    or len(stored) != len(query)
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        for value in stored
                    )
                ):
                    continue
                values = [float(value) for value in stored]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stored_norm = math.sqrt(sum(value * value for value in values))
            if stored_norm <= 1e-12:
                continue
            cosine = sum(
                left * right for left, right in zip(query, values, strict=True)
            ) / (query_norm * stored_norm)
            score = max(0.0, min(1.0, cosine))
            if score >= float(minimum_score):
                hits.append(MemorySearchHit(memory=records[memory_id], score=score))

        hits.sort(key=lambda hit: (hit.score, hit.memory.updated_at), reverse=True)
        return hits[:limit]

    def merge(
        self,
        source_memory_ids: tuple[str, str],
        merged_memory: MemoryRecord,
        *,
        event_store: EventStore | None = None,
        task_run_store=None,
        now: datetime | None = None,
    ) -> MemoryRecord:
        """Atomically supersede two active memories and preserve their lineage.

        The merged record must retain every source event reference, cannot reduce
        sensitivity, cannot outlive either source's earliest expiry, and cannot claim
        confidence higher than the least-confident source. The caller supplies the
        merged content explicitly; no model-generated rewrite is accepted implicitly.
        """
        if (
            not isinstance(source_memory_ids, tuple)
            or len(source_memory_ids) != 2
            or not all(isinstance(value, str) and value for value in source_memory_ids)
        ):
            raise ValueError("exactly two non-empty source memory IDs are required")
        if source_memory_ids[0] == source_memory_ids[1]:
            raise ValueError("a memory cannot be merged with itself")
        if merged_memory.supersedes_id is not None:
            raise ValueError("merge records use explicit two-parent lineage, not supersedes_id")

        current = self._aware_utc(now or datetime.now(timezone.utc), "now")
        if merged_memory.created_at.tzinfo is None:
            raise ValueError("merged memory created_at must be timezone-aware")
        if merged_memory.created_at.astimezone(timezone.utc) < current:
            # The saved record is timestamped at commit time, not with an old draft time.
            merged_memory = merged_memory.model_copy(update={"created_at": current})

        required_event_ids: set[str] = set()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                placeholders = ",".join("?" for _ in source_memory_ids)
                rows = db.execute(
                    f"SELECT memory_id, status, payload FROM memories "
                    f"WHERE memory_id IN ({placeholders})",
                    source_memory_ids,
                ).fetchall()
                by_id = {row[0]: row for row in rows}
                if set(by_id) != set(source_memory_ids):
                    raise ValueError("one or more source memories were not found")
                sources: list[MemoryRecord] = []
                for memory_id in source_memory_ids:
                    _, status, payload = by_id[memory_id]
                    if status != "active":
                        raise ValueError("only active memories can be merged")
                    source = MemoryRecord.model_validate_json(payload)
                    if source.expires_at is not None:
                        if source.expires_at.astimezone(timezone.utc) <= current:
                            raise ValueError("expired memories cannot be merged")
                    sources.append(source)

                if sources[0].kind != sources[1].kind:
                    raise ValueError("source memories must have the same kind")
                if merged_memory.kind != sources[0].kind:
                    raise ValueError("merged memory must preserve the source memory kind")

                sensitivity_order = {"public": 0, "internal": 1, "sensitive": 2}
                required_sensitivity = max(
                    (item.sensitivity for item in sources),
                    key=sensitivity_order.__getitem__,
                )
                if sensitivity_order[merged_memory.sensitivity] < sensitivity_order[required_sensitivity]:
                    raise ValueError("merged memory cannot reduce source sensitivity")

                minimum_confidence = min(item.confidence for item in sources)
                if merged_memory.confidence > minimum_confidence:
                    raise ValueError("merged memory confidence cannot exceed the least-confident source")

                for source in sources:
                    required_event_ids.update(source.source_event_ids)
                required_run_ids = {
                    run_id for source in sources for run_id in source.source_task_run_ids
                }
                if not required_event_ids.issubset(set(merged_memory.source_event_ids)):
                    raise ValueError("merged memory must retain all source event provenance")
                if not required_run_ids.issubset(set(merged_memory.source_task_run_ids)):
                    raise ValueError("merged memory must retain all source task-run provenance")

                expiries = [
                    item.expires_at.astimezone(timezone.utc)
                    for item in sources if item.expires_at is not None
                ]
                if expiries:
                    if merged_memory.expires_at is None:
                        raise ValueError("merged memory must preserve the earliest source expiry")
                    merged_expiry = merged_memory.expires_at.astimezone(timezone.utc)
                    if merged_expiry > min(expiries):
                        raise ValueError("merged memory cannot outlive its earliest-expiring source")

                if required_event_ids:
                    if event_store is None:
                        raise ValueError("event_store is required to verify merged provenance")
                    missing = [
                        event_id for event_id in sorted(required_event_ids)
                        if event_store.get(event_id) is None
                    ]
                    if missing:
                        raise ValueError(f"source event not found: {missing[0]}")
                if required_run_ids:
                    if task_run_store is None or not callable(getattr(task_run_store, "get", None)):
                        raise ValueError("task_run_store is required to verify merged task-run provenance")
                    for run_id in sorted(required_run_ids):
                        source_run = task_run_store.get(run_id)
                        if source_run is None or source_run.status != "completed":
                            raise ValueError("merged source task runs must exist and be completed")

                normalized = merged_memory.model_copy(
                    update={
                        "created_at": current,
                        "updated_at": current,
                        "source_event_ids": sorted(set(merged_memory.source_event_ids)),
                    }
                )
                db.execute(
                    """INSERT INTO memories
                    (memory_id, kind, sensitivity, status, created_at, expires_at, payload)
                    VALUES (?, ?, ?, 'active', ?, ?, ?)""",
                    (
                        normalized.memory_id,
                        normalized.kind,
                        normalized.sensitivity,
                        current.isoformat(),
                        normalized.expires_at.isoformat() if normalized.expires_at else None,
                        normalized.model_dump_json(),
                    ),
                )
                db.executemany(
                    "UPDATE memories SET status = 'superseded' WHERE memory_id = ?",
                    [(memory_id,) for memory_id in source_memory_ids],
                )
                db.executemany(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?",
                    [(memory_id,) for memory_id in source_memory_ids],
                )
                db.executemany(
                    """INSERT INTO memory_lineage
                    (memory_id, source_memory_id, relation, created_at)
                    VALUES (?, ?, 'merged_from', ?)""",
                    [(normalized.memory_id, memory_id, current.isoformat())
                     for memory_id in source_memory_ids],
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return normalized

    def lineage(self, memory_id: str) -> tuple[str, ...]:
        """Return source IDs from which a reviewed merged memory was composed."""
        with self._connect() as db:
            rows = db.execute(
                """SELECT source_memory_id FROM memory_lineage
                WHERE memory_id = ? AND relation = 'merged_from'
                ORDER BY source_memory_id ASC""",
                (memory_id,),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def delete(self, memory_id: str) -> bool:
        with self._connect() as db:
            db.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,))
            cursor = db.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            return cursor.rowcount > 0

    def count_expired(self, *, now: datetime | None = None) -> int:
        current = self._aware_utc(now or datetime.now(timezone.utc), "now")
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (current.isoformat(),),
            ).fetchone()
        return int(row[0])

    def prune_expired(self, *, now: datetime | None = None) -> int:
        current = self._aware_utc(now or datetime.now(timezone.utc), "now")
        with self._connect() as db:
            expired = db.execute(
                "SELECT memory_id FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (current.isoformat(),),
            ).fetchall()
            ids = [row[0] for row in expired]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                db.execute(
                    f"DELETE FROM memory_embeddings WHERE memory_id IN ({placeholders})",
                    ids,
                )
                cursor = db.execute(
                    f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                    ids,
                )
                return int(cursor.rowcount)
            return 0

    def count(self, *, include_superseded: bool = True) -> int:
        where = "" if include_superseded else " WHERE status = 'active'"
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM memories" + where).fetchone()[0])
