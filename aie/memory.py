"""Explicit, provenance-aware local memory records; no automatic consolidation."""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

MEMORY_KINDS = {"working", "episodic", "semantic", "procedural", "prospective"}
SENSITIVITY_LEVELS = {"public", "internal", "sensitive"}
VERIFICATION_STATES = {"unverified", "supported", "disputed", "verified"}
MAX_CONTENT_CHARS = 16000
MAX_PROVENANCE_IDS = 64
MAX_TAGS = 32


class MemoryStore:
    """Small local SQLite memory API with explicit write/delete and bounded retrieval."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                sensitivity TEXT NOT NULL,
                verification TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                access_count INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_kind_created "
                "ON memories(kind, created_at DESC)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_expiry ON memories(expires_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def add(
        self,
        content: str,
        *,
        kind: str = "episodic",
        provenance_ids: list[str] | None = None,
        confidence: float = 0.5,
        sensitivity: str = "internal",
        verification: str = "unverified",
        tags: list[str] | None = None,
        ttl_days: int | None = None,
    ) -> dict[str, Any]:
        if kind not in MEMORY_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(MEMORY_KINDS))}")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"content must contain 1..{MAX_CONTENT_CHARS} characters")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be finite and between 0 and 1")
        if sensitivity not in SENSITIVITY_LEVELS:
            raise ValueError("invalid sensitivity level")
        if verification not in VERIFICATION_STATES:
            raise ValueError("invalid verification state")
        provenance_ids = provenance_ids or []
        if (
            not isinstance(provenance_ids, list) or len(provenance_ids) > MAX_PROVENANCE_IDS
            or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in provenance_ids)
        ):
            raise ValueError(f"provenance_ids must contain at most {MAX_PROVENANCE_IDS} non-empty IDs")
        tags = tags or []
        if not isinstance(tags, list) or len(tags) > MAX_TAGS or any(
            not isinstance(tag, str) or not tag.strip() or len(tag) > 64 for tag in tags
        ):
            raise ValueError(f"tags must contain at most {MAX_TAGS} non-empty strings")
        if ttl_days is not None and (
            isinstance(ttl_days, bool) or not isinstance(ttl_days, int) or not 1 <= ttl_days <= 36500
        ):
            raise ValueError("ttl_days must be between 1 and 36500")
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=ttl_days)).isoformat() if ttl_days else None
        memory_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                """INSERT INTO memories(
                    memory_id, kind, content, provenance_json, confidence,
                    sensitivity, verification, tags_json, created_at, updated_at,
                    expires_at, access_count
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    memory_id, kind, content, json.dumps(provenance_ids),
                    float(confidence), sensitivity, verification, json.dumps(tags),
                    now.isoformat(), now.isoformat(), expires,
                ),
            )
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict[str, Any] | None:
        if not isinstance(memory_id, str) or not memory_id or len(memory_id) > 64:
            raise ValueError("memory_id must contain 1..64 characters")
        with self._connect() as db:
            row = db.execute(
                """SELECT * FROM memories WHERE memory_id = ?
                   AND (expires_at IS NULL OR expires_at > ?)""",
                (memory_id, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE memory_id = ?",
                (memory_id,),
            )
        return _decode(row, incremented=True)

    def search(
        self,
        query: str = "",
        *,
        kind: str | None = None,
        include_sensitive: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("query must be a string of at most 1000 characters")
        if kind is not None and kind not in MEMORY_KINDS:
            raise ValueError("invalid memory kind")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        now = datetime.now(timezone.utc).isoformat()
        clauses = ["(expires_at IS NULL OR expires_at > ?)"]
        args: list[Any] = [now]
        if kind is not None:
            clauses.append("kind = ?")
            args.append(kind)
        if not include_sensitive:
            clauses.append("sensitivity != 'sensitive'")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memories WHERE " + " AND ".join(clauses)
                + " ORDER BY created_at DESC, memory_id ASC LIMIT 500",
                args,
            ).fetchall()
        terms = [term.casefold() for term in query.split() if term]
        records = [_decode(row) for row in rows]
        if terms:
            def score(record: dict[str, Any]) -> tuple[int, str]:
                haystack = (record["content"] + " " + " ".join(record["tags"])).casefold()
                return sum(term in haystack for term in terms), record["memory_id"]
            records = [record for record in records if score(record)[0] > 0]
            records.sort(key=lambda record: (
                -score(record)[0],
                -datetime.fromisoformat(record["created_at"]).timestamp(),
                record["memory_id"],
            ))
        return records[:limit]


    def revise(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        confidence: float | None = None,
        verification: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """Explicitly correct a memory without silently changing its provenance."""
        if not isinstance(memory_id, str) or not memory_id or len(memory_id) > 64:
            raise ValueError("memory_id must contain 1..64 characters")
        updates: dict[str, Any] = {}
        if content is not None:
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT_CHARS:
                raise ValueError(f"content must contain 1..{MAX_CONTENT_CHARS} characters")
            updates["content"] = content
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("confidence must be finite and between 0 and 1")
            updates["confidence"] = float(confidence)
        if verification is not None:
            if verification not in VERIFICATION_STATES:
                raise ValueError("invalid verification state")
            updates["verification"] = verification
        if tags is not None:
            if not isinstance(tags, list) or len(tags) > MAX_TAGS or any(
                not isinstance(tag, str) or not tag.strip() or len(tag) > 64 for tag in tags
            ):
                raise ValueError(f"tags must contain at most {MAX_TAGS} non-empty strings")
            updates["tags_json"] = json.dumps(tags)
        if not updates:
            raise ValueError("at least one field must be supplied for revision")
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        with self._connect() as db:
            cursor = db.execute(
                f"UPDATE memories SET {assignments} WHERE memory_id = ?",
                (*updates.values(), memory_id),
            )
            return cursor.rowcount == 1

    def export_jsonl(self, destination: Path, *, include_sensitive: bool = False) -> int:
        """Export active memory records; sensitive export requires an explicit opt-in."""
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError("export destination must not be the SQLite database")
        # Export pages the underlying table rather than using the bounded interactive search.
        now = datetime.now(timezone.utc).isoformat()
        clause = "(expires_at IS NULL OR expires_at > ?)"
        args: list[Any] = [now]
        if not include_sensitive:
            clause += " AND sensitivity != 'sensitive'"
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM memories WHERE " + clause
                + " ORDER BY created_at ASC, memory_id ASC",
                args,
            ).fetchall()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8", newline="\\n") as handle:
            for row in rows:
                handle.write(json.dumps(_decode(row), ensure_ascii=False, allow_nan=False) + "\\n")
        return len(rows)

    def delete(self, memory_id: str) -> bool:
        if not isinstance(memory_id, str) or not memory_id or len(memory_id) > 64:
            raise ValueError("memory_id must contain 1..64 characters")
        with self._connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            return cursor.rowcount == 1

    def prune_expired(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now.astimezone(timezone.utc).isoformat(),),
            )
            return cursor.rowcount


def _decode(row: tuple, *, incremented: bool = False) -> dict[str, Any]:
    return {
        "memory_id": row[0],
        "kind": row[1],
        "content": row[2],
        "provenance_ids": json.loads(row[3]),
        "confidence": float(row[4]),
        "sensitivity": row[5],
        "verification": row[6],
        "tags": json.loads(row[7]),
        "created_at": row[8],
        "updated_at": row[9],
        "expires_at": row[10],
        "access_count": int(row[11]) + (1 if incremented else 0),
    }
