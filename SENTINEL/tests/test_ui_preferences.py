import json
import sqlite3
import threading

import pytest

from sentinel import ui_preferences


@pytest.fixture
def isolated_ui_preferences_db(monkeypatch):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    lock = threading.RLock()

    def db(sql, params=()):
        with lock:
            cursor = connection.execute(sql, params)
            has_rows = cursor.description is not None
            rows = cursor.fetchall() if has_rows else []
            connection.commit()
            return rows if has_rows else cursor.lastrowid

    monkeypatch.setattr(ui_preferences.core, "db", db)
    ui_preferences.ensure_schema()
    return connection


def test_navigation_preferences_default_to_simple_and_persist_full_mode(isolated_ui_preferences_db):
    connection = isolated_ui_preferences_db
    assert ui_preferences.settings() == {"navigation_mode": "simple"}

    saved = ui_preferences.update({"navigation_mode": "full"})
    assert saved == {"navigation_mode": "full"}

    row = connection.execute(
        "SELECT value_json FROM ui_preferences WHERE preference_key='navigation_mode'"
    ).fetchone()
    assert json.loads(row[0]) == "full"
    assert ui_preferences.settings()["navigation_mode"] == "full"

    ui_preferences.update({"navigation_mode": "simple"})
    assert ui_preferences.settings()["navigation_mode"] == "simple"


def test_navigation_preferences_reject_unknown_or_unsafe_values(isolated_ui_preferences_db):
    with pytest.raises(ValueError, match="unknown UI preference"):
        ui_preferences.update({"run_repairs_automatically": True})
    with pytest.raises(ValueError, match="navigation_mode"):
        ui_preferences.update({"navigation_mode": "hidden"})
    with pytest.raises(ValueError, match="non-empty"):
        ui_preferences.update({})


def test_ui_preference_reads_tolerate_corrupt_persisted_json(isolated_ui_preferences_db):
    connection = isolated_ui_preferences_db
    connection.execute(
        "UPDATE ui_preferences SET value_json='not-json' WHERE preference_key='navigation_mode'"
    )
    connection.commit()
    assert ui_preferences.settings() == {"navigation_mode": "simple"}
