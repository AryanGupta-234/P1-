"""Task context: ongoing objectives SENTI tracks across sessions.

Tasks are sir's objectives (e.g. "get the Wi-Fi drops fixed"), with status, progress
notes and an optional due time. Open tasks are offered to the model as context each turn,
so SENTI can follow up on unfinished work. The pack owns its own table.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from senti.tools.registry import CapabilityRegistry, ToolDefinition

STATUSES = ("open", "in_progress", "blocked", "done")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
    notes_json TEXT NOT NULL DEFAULT '[]', due_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, updated_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check_due(due_at: str | None) -> str | None:
    if due_at is None:
        return None
    try:
        parsed = datetime.fromisoformat(due_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("due_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # interpret as local time
    return parsed.isoformat(timespec="seconds")


class TaskBook:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript(_SCHEMA)

    def _row(self, row) -> dict[str, Any]:
        return {"task_id": row["task_id"], "title": row["title"], "status": row["status"],
                "notes": json.loads(row["notes_json"]), "due_at": row["due_at"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def create(self, title: str, *, due_at: str | None = None, note: str | None = None) -> dict[str, Any]:
        if not isinstance(title, str) or not 2 <= len(title.strip()) <= 200:
            raise ValueError("title must contain 2 to 200 characters")
        task_id, now = str(uuid4()), _now()
        notes = [{"at": now, "note": note.strip()[:500]}] if note and note.strip() else []
        with self.store.connect() as db:
            db.execute("INSERT INTO tasks(task_id, title, status, notes_json, due_at, created_at, updated_at) "
                       "VALUES (?, ?, 'open', ?, ?, ?, ?)",
                       (task_id, title.strip(), json.dumps(notes), _check_due(due_at), now, now))
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("No task matched that identifier.")
        return self._row(row)

    def update(self, task_id: str, *, status: str | None = None, note: str | None = None,
               due_at: str | None = None) -> dict[str, Any]:
        task = self.get(task_id)
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        notes = task["notes"]
        if note and note.strip():
            notes = (notes + [{"at": _now(), "note": note.strip()[:500]}])[-30:]
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status=?, notes_json=?, due_at=COALESCE(?, due_at), updated_at=? "
                       "WHERE task_id=?", (status or task["status"], json.dumps(notes), _check_due(due_at),
                                           _now(), task_id))
        return self.get(task_id)

    def list(self, *, include_done: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM tasks" + ("" if include_done else " WHERE status != 'done'") + \
                " ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END, updated_at DESC LIMIT ?"
        with self.store.connect() as db:
            rows = db.execute(query, (max(1, min(limit, 100)),)).fetchall()
        return [self._row(r) for r in rows]

    def context(self, limit: int = 5) -> list[dict[str, Any]]:
        """Compact open-task view for the model's per-turn context."""
        return [{"task_id": t["task_id"], "title": t["title"], "status": t["status"],
                 **({"due_at": t["due_at"]} if t["due_at"] else {}),
                 **({"last_note": t["notes"][-1]["note"]} if t["notes"] else {})}
                for t in self.list(limit=limit)]


def register_task_tools(registry: CapabilityRegistry, store, settings=None) -> TaskBook:
    book = TaskBook(store)
    registry.register(ToolDefinition(
        name="senti_list_tasks",
        description="List sir's tracked objectives and their status, progress notes and due times.",
        parameters={"type": "object", "properties": {"include_done": {"type": "boolean"}},
                    "additionalProperties": False},
        risk="read_only",
        handler=lambda args: {"summary": "Listed tracked tasks.",
                              "tasks": book.list(include_done=args.get("include_done", False)),
                              "verified": True},
    ))
    registry.register(ToolDefinition(
        name="senti_track_task",
        description="Start tracking a new objective for sir so SENTI can follow up on it across sessions.",
        parameters={"type": "object", "properties": {
            "title": {"type": "string", "minLength": 2, "maxLength": 200},
            "note": {"type": "string", "maxLength": 500},
            "due_at": {"type": "string", "maxLength": 40}},
            "required": ["title"], "additionalProperties": False},
        risk="low",
        handler=lambda args: {"summary": "Now tracking this objective.",
                              "task": book.create(args["title"], due_at=args.get("due_at"), note=args.get("note")),
                              "verified": True},
        simulate=lambda args: {"intended_state": {"title": args["title"], "status": "open",
                                                  "due_at": _check_due(args.get("due_at"))},
                               "effect": "Adds a tracked objective to SENTI's task list.",
                               "recovery": "Mark it done or update it later."},
    ))

    def _simulate_update(args: dict) -> dict:
        current = book.get(args["task_id"])
        return {"current_state": {"title": current["title"], "status": current["status"]},
                "intended_state": {k: v for k, v in args.items() if k != "task_id"},
                "effect": "Updates the tracked objective.", "recovery": "Update it again."}

    registry.register(ToolDefinition(
        name="senti_update_task",
        description="Update a tracked objective: change status (open, in_progress, blocked, done), add a progress note or set a due time.",
        parameters={"type": "object", "properties": {
            "task_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "status": {"type": "string", "enum": list(STATUSES)},
            "note": {"type": "string", "maxLength": 500},
            "due_at": {"type": "string", "maxLength": 40}},
            "required": ["task_id"], "additionalProperties": False},
        risk="low",
        handler=lambda args: {"summary": "Task updated.",
                              "task": book.update(args["task_id"], status=args.get("status"),
                                                  note=args.get("note"), due_at=args.get("due_at")),
                              "verified": True},
        simulate=_simulate_update,
    ))
    return book
