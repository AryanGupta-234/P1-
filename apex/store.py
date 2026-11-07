"""Single-file APEX data store for profile, conversations, memory, apps and tasks."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from apex.config import apex_data_dir


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class UnifiedDataStore:
    """One canonical SQLite file; all feature modules use this repository facade."""

    SCHEMA_VERSION = 1
    _SENSITIVE_KEYS = ("password", "passwd", "token", "secret", "credential", "cookie", "private_key")

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else apex_data_dir() / "apex-unified.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open one bounded connection and always close it after commit/rollback."""
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assistant_profile (
            profile_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            role TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, memory_type TEXT NOT NULL,
            payload_json TEXT NOT NULL, source TEXT NOT NULL, sensitivity TEXT NOT NULL,
            confidence REAL, expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_memories_namespace_type ON memories(namespace, memory_type);
        CREATE TABLE IF NOT EXISTS app_catalog (
            app_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, executable_path TEXT,
            aumid TEXT, aliases_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}',
            trust_state TEXT NOT NULL DEFAULT 'unknown', source TEXT NOT NULL,
            available INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_runs (
            run_id TEXT PRIMARY KEY, status TEXT NOT NULL, request TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_steps (
            step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES task_runs(run_id),
            capability_id TEXT NOT NULL, status TEXT NOT NULL, receipt_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS store_changes (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
            record_id TEXT NOT NULL, operation TEXT NOT NULL, changed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runtime_flags (
            flag_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
        with self._lock, self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(schema)
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (self.SCHEMA_VERSION, utc_now()),
            )

    def _change(self, db: sqlite3.Connection, domain: str, record_id: str, operation: str) -> None:
        db.execute(
            "INSERT INTO store_changes(domain, record_id, operation, changed_at) VALUES (?, ?, ?, ?)",
            (domain, record_id, operation, utc_now()),
        )

    @classmethod
    def _validate_memory_payload(cls, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict) or not payload or len(payload) > 20:
            raise ValueError("memory payload must be a non-empty object with at most 20 fields")

        def inspect(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if any(token in str(key).casefold() for token in cls._SENSITIVE_KEYS):
                        raise ValueError("credential-like memory fields are not permitted")
                    inspect(child)
            elif isinstance(value, list):
                if len(value) > 50:
                    raise ValueError("memory lists may contain at most 50 values")
                for child in value:
                    inspect(child)
            elif isinstance(value, str) and len(value) > 2000:
                raise ValueError("individual memory strings may not exceed 2000 characters")
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError("memory values must be JSON-compatible primitives, objects or lists")

        inspect(payload)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 8_192:
            raise ValueError("memory payload exceeds 8 KiB")
        return encoded

    def save_profile(self, profile: dict[str, Any]) -> None:
        if not isinstance(profile, dict) or len(profile) > 40:
            raise ValueError("profile must be an object with at most 40 fields")
        if any(any(part in str(key).casefold() for part in self._SENSITIVE_KEYS) for key in profile):
            raise ValueError("credential-like profile fields are not permitted")
        payload = json.dumps(profile, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > 32_000:
            raise ValueError("profile payload exceeds 32 KiB")
        profile_id = "primary"
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO assistant_profile(profile_id, profile_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(profile_id) DO UPDATE SET profile_json=excluded.profile_json, "
                "version=assistant_profile.version+1, updated_at=excluded.updated_at",
                (profile_id, payload, utc_now()),
            )
            self._change(db, "profile", profile_id, "upsert")

    def get_profile(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT profile_json FROM assistant_profile WHERE profile_id='primary'").fetchone()
        return json.loads(row[0]) if row else {"preferred_salutation": "sir"}

    def ensure_conversation(self, conversation_id: str | None = None) -> str:
        identifier = conversation_id or str(uuid4())
        now = utc_now()
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO conversations(conversation_id, created_at, updated_at) VALUES (?, ?, ?)",
                (identifier, now, now),
            )
            self._change(db, "conversation", identifier, "touch")
        return identifier

    def append_message(self, conversation_id: str, role: str, content: str, metadata: dict | None = None) -> str:
        message_id = str(uuid4())
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO messages(message_id, conversation_id, role, content, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content[:40_000], json.dumps(metadata or {}, ensure_ascii=False), utc_now()),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE conversation_id=?", (utc_now(), conversation_id))
            self._change(db, "message", message_id, "insert")
        return message_id

    def recent_messages(self, conversation_id: str, limit: int = 20) -> list[dict[str, str]]:
        limit = max(1, min(int(limit), 32))
        with self.connect() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    def add_memory(self, *, namespace: str, memory_type: str, payload: dict, source: str,
                   sensitivity: str = "normal", confidence: float | None = None,
                   expires_at: str | None = None) -> str:
        for label, value in (("namespace", namespace), ("memory_type", memory_type), ("source", source)):
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
                raise ValueError(f"{label} must contain 1 to 80 characters")
        if sensitivity not in {"normal", "sensitive"}:
            raise ValueError("sensitivity must be normal or sensitive")
        if confidence is not None and (isinstance(confidence, bool) or not 0.0 <= confidence <= 1.0):
            raise ValueError("confidence must be between 0 and 1")
        if expires_at is not None:
            try:
                parsed_expiry = datetime.fromisoformat(expires_at)
            except (TypeError, ValueError) as exc:
                raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
            if parsed_expiry.tzinfo is None:
                raise ValueError("expires_at must include a timezone")
        payload_json = self._validate_memory_payload(payload)
        memory_id = str(uuid4())
        now = utc_now()
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO memories(memory_id, namespace, memory_type, payload_json, source, sensitivity, "
                "confidence, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (memory_id, namespace.strip(), memory_type.strip(), payload_json,
                 source.strip(), sensitivity, confidence, expires_at, now, now),
            )
            self._change(db, "memory", memory_id, "insert")
        return memory_id

    def search_memories(self, query: str = "", *, namespace: str = "personal",
                        limit: int = 20, include_sensitive: bool = False) -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 500:
            raise ValueError("memory query must be a string of at most 500 characters")
        if not isinstance(namespace, str) or not 1 <= len(namespace) <= 80:
            raise ValueError("memory namespace is invalid")
        if isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("memory limit must be between 1 and 50")
        terms = list(dict.fromkeys(re.findall(r"[\w-]{3,}", query.casefold())))[:8]
        clauses = []
        params: list[Any] = [namespace, utc_now()]
        if terms:
            clauses.append("(" + " OR ".join("lower(payload_json) LIKE ?" for _ in terms) + ")")
            params.extend(f"%{term}%" for term in terms)
        if not include_sensitive:
            clauses.append("sensitivity='normal'")
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(
                "SELECT memory_id, namespace, memory_type, payload_json, source, sensitivity, "
                "confidence, expires_at, created_at, updated_at FROM memories "
                "WHERE namespace=? AND (expires_at IS NULL OR expires_at>?) AND " + where +
                " ORDER BY updated_at DESC LIMIT ?", params,
            ).fetchall()
        return [
            {**dict(row), "payload": json.loads(row["payload_json"])}
            for row in rows
        ]

    def forget_memory(self, memory_id: str) -> bool:
        if not isinstance(memory_id, str) or not 1 <= len(memory_id) <= 64:
            raise ValueError("memory_id is invalid")
        with self._lock, self.connect() as db:
            row = db.execute("SELECT memory_id FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
            if row is None:
                return False
            db.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
            self._change(db, "memory", memory_id, "delete")
        return True

    def prune_expired_memories(self) -> int:
        now = utc_now()
        with self._lock, self.connect() as db:
            rows = db.execute(
                "SELECT memory_id FROM memories WHERE expires_at IS NOT NULL AND expires_at<=?", (now,)
            ).fetchall()
            if not rows:
                return 0
            db.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at<=?", (now,))
            for row in rows:
                self._change(db, "memory", row["memory_id"], "expire")
        return len(rows)

    def set_runtime_flag(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not 1 <= len(key) <= 80:
            raise ValueError("runtime flag key is invalid")
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > 2_048:
            raise ValueError("runtime flag value exceeds 2 KiB")
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO runtime_flags(flag_key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(flag_key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, payload, utc_now()),
            )
            self._change(db, "runtime_flag", key, "upsert")

    def get_runtime_flag(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM runtime_flags WHERE flag_key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def upsert_app(self, *, display_name: str, executable_path: str | None, aumid: str | None = None,
                   aliases: list[str] | None = None, metadata: dict[str, Any] | None = None,
                   trust_state: str = "unknown", source: str = "unknown", available: bool = False) -> str:
        identity = (executable_path or aumid or display_name).casefold().encode("utf-8")
        app_id = hashlib.sha256(identity).hexdigest()[:32]
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO app_catalog(app_id, display_name, executable_path, aumid, aliases_json, metadata_json, "
                "trust_state, source, available, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(app_id) DO UPDATE SET display_name=excluded.display_name, "
                "executable_path=excluded.executable_path, aumid=excluded.aumid, aliases_json=excluded.aliases_json, "
                "metadata_json=excluded.metadata_json, trust_state=excluded.trust_state, source=excluded.source, "
                "available=excluded.available, updated_at=excluded.updated_at",
                (app_id, display_name[:200], executable_path, aumid,
                 json.dumps((aliases or [])[:50], ensure_ascii=False),
                 json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False), trust_state[:40], source[:80],
                 int(bool(available)), utc_now()),
            )
            self._change(db, "app_catalog", app_id, "upsert")
        return app_id

    def list_apps(self, limit: int = 500) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 2000))
        with self.connect() as db:
            rows = db.execute(
                "SELECT app_id, display_name, executable_path, aumid, aliases_json, metadata_json, "
                "trust_state, source, available, updated_at FROM app_catalog ORDER BY display_name LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["aliases"] = json.loads(item.pop("aliases_json"))
            item["metadata"] = json.loads(item.pop("metadata_json"))
            item["available"] = bool(item["available"])
            result.append(item)
        return result

    def recent_changes(self, after_sequence: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self.connect() as db:
            rows = db.execute(
                "SELECT sequence, domain, record_id, operation, changed_at FROM store_changes "
                "WHERE sequence>? ORDER BY sequence LIMIT ?", (max(0, after_sequence), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_audit(self, event_type: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid4())
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO audit_events(event_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (event_id, event_type, json.dumps(payload, ensure_ascii=False, allow_nan=False), utc_now()),
            )
            self._change(db, "audit", event_id, "append")
        return event_id

    def integrity_check(self) -> bool:
        with self.connect() as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
        return bool(result and result[0] == "ok")
