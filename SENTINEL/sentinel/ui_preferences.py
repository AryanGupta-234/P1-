"""SQLite-backed presentation preferences for the SENTINEL operator HUD.

These preferences affect navigation and display only. They do not change agent
policy, collection, diagnosis, execution authority or Windows state.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import core

DEFAULTS: dict[str, Any] = {
    "navigation_mode": "simple",
}


def ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS ui_preferences(
        preference_key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at REAL NOT NULL
    )""")
    now = time.time()
    for key, value in DEFAULTS.items():
        core.db(
            "INSERT OR IGNORE INTO ui_preferences(preference_key,value_json,updated_at) VALUES(?,?,?)",
            (key, json.dumps(value, separators=(",", ":")), now),
        )


def settings() -> dict[str, Any]:
    values = dict(DEFAULTS)
    for key, raw in core.db("SELECT preference_key,value_json FROM ui_preferences"):
        if key in DEFAULTS:
            try:
                values[key] = json.loads(raw)
            except (TypeError, ValueError):
                pass
    return values


def update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("UI preferences must be a non-empty object")
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise ValueError("unknown UI preference: " + ", ".join(sorted(unknown)))
    mode = payload.get("navigation_mode")
    if mode is not None and mode not in ("simple", "full"):
        raise ValueError("navigation_mode must be 'simple' or 'full'")
    now = time.time()
    for key, value in payload.items():
        core.db(
            "INSERT INTO ui_preferences(preference_key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(preference_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
            (key, json.dumps(value, separators=(",", ":")), now),
        )
    return settings()


ensure_schema()
