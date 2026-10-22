import json
import sqlite3
import threading
from datetime import datetime

import pytest

from sentinel import activity_engine


def isolated_activity_db(monkeypatch):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript("""
        CREATE TABLE activity_tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            terms_json TEXT NOT NULL,
            app_keys_json TEXT NOT NULL,
            observations INTEGER NOT NULL DEFAULT 0,
            foreground_seconds REAL NOT NULL DEFAULT 0,
            active_seconds REAL NOT NULL DEFAULT 0,
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL
        );
        CREATE TABLE activity_apps(
            app_key TEXT PRIMARY KEY, app_name TEXT NOT NULL,
            executable TEXT NOT NULL DEFAULT '', first_seen REAL NOT NULL,
            last_seen REAL NOT NULL, focus_sessions INTEGER NOT NULL DEFAULT 0,
            foreground_seconds REAL NOT NULL DEFAULT 0,
            active_seconds REAL NOT NULL DEFAULT 0,
            last_window_class TEXT NOT NULL DEFAULT '',
            latest_terms_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE activity_sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, app_key TEXT NOT NULL,
            app_name TEXT NOT NULL, executable TEXT NOT NULL DEFAULT '',
            pid INTEGER, process_created REAL, window_class TEXT NOT NULL DEFAULT '',
            started_at REAL NOT NULL, ended_at REAL, foreground_seconds REAL NOT NULL DEFAULT 0,
            active_seconds REAL NOT NULL DEFAULT 0, idle_seconds REAL NOT NULL DEFAULT 0,
            task_id INTEGER, semantic_terms_json TEXT NOT NULL DEFAULT '[]',
            weekday_local INTEGER NOT NULL, hour_local INTEGER NOT NULL,
            is_fullscreen INTEGER NOT NULL DEFAULT 0, is_game INTEGER NOT NULL DEFAULT 0,
            interrupted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE activity_transitions(
            from_app_key TEXT NOT NULL, to_app_key TEXT NOT NULL,
            weekday_local INTEGER NOT NULL, hour_local INTEGER NOT NULL,
            observations INTEGER NOT NULL DEFAULT 0, last_seen REAL NOT NULL,
            PRIMARY KEY(from_app_key,to_app_key,weekday_local,hour_local)
        );
        CREATE TABLE activity_launches(
            app_key TEXT PRIMARY KEY, last_launch REAL NOT NULL,
            launch_count INTEGER NOT NULL DEFAULT 0, last_result TEXT NOT NULL DEFAULT ''
        );
    """)
    monkeypatch.setattr(activity_engine.core, "_db", connection)
    monkeypatch.setattr(activity_engine.core, "_db_lock", threading.Lock())
    return connection


def test_semantic_terms_redact_urls_and_email_addresses():
    terms = activity_engine.semantic_terms(
        "Python automation notes https://private.example/user?id=123 mail me@example.com",
        "ResearchApp.exe",
    )
    joined = " ".join(terms)
    assert "python" in terms
    assert "automation" in terms
    assert "researchapp" in terms
    assert "private" not in joined
    assert "example" not in joined
    assert "me" not in terms


def test_credential_oriented_window_titles_are_not_semantically_indexed():
    terms = activity_engine.semantic_terms("Password manager - recovery code 983441", "Browser.exe")
    assert terms == ["browser"]


def test_semantic_task_clusters_form_from_observed_term_overlap(monkeypatch):
    connection = isolated_activity_db(monkeypatch)
    first = activity_engine._task_cluster(
        ["python", "automation"], "app-a", "Editor", 50, 45, 1000
    )
    second = activity_engine._task_cluster(
        ["python", "automation", "scheduler"], "app-b", "Terminal", 40, 37, 1100
    )
    assert first == second
    row = connection.execute(
        "SELECT label,terms_json,app_keys_json,observations,active_seconds FROM activity_tasks WHERE id=?",
        (first,),
    ).fetchone()
    assert row[0] == "python · automation · scheduler"
    assert set(json.loads(row[1])) == {"python", "automation", "scheduler"}
    assert set(json.loads(row[2])) == {"app-a", "app-b"}
    assert row[3] == 2
    assert row[4] == 82


def test_learned_app_launch_paths_must_be_inside_observed_local_app_roots(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    root.mkdir()
    executable = root / "ObservedApp.exe"
    executable.write_bytes(b"test")
    outside = tmp_path / "downloads" / "Untrusted.exe"
    outside.parent.mkdir()
    outside.write_bytes(b"test")
    monkeypatch.setattr(activity_engine, "IS_WIN", True)
    monkeypatch.setenv("ProgramFiles", str(root))
    monkeypatch.setenv("ProgramFiles(x86)", str(root))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert activity_engine._safe_launch_path(str(executable))
    assert not activity_engine._safe_launch_path(str(outside))
    assert not activity_engine._safe_launch_path(str(root / "missing.exe"))


def test_auto_launch_waits_for_a_stable_active_context(monkeypatch):
    calls = []
    settings = dict(activity_engine.DEFAULT_SETTINGS)
    settings["auto_launch_learned_apps"] = True
    monkeypatch.setattr(activity_engine, "_settings", lambda: settings)
    monkeypatch.setattr(activity_engine, "_suggestions", lambda *args: calls.append("suggested") or [])
    current = {
        "app_key": "current-app", "active_seconds": 12, "idle_seconds": 0,
        "is_game": False, "fullscreen": False,
    }
    activity_engine._maybe_auto_launch(current, 10000)
    assert calls == []
    current["active_seconds"] = 60
    activity_engine._maybe_auto_launch(current, 10001)
    assert calls == ["suggested"]


def test_activity_settings_reject_out_of_range_and_non_boolean_values(monkeypatch):
    monkeypatch.setattr(activity_engine.core, "CFG", {"activity": dict(activity_engine.DEFAULT_SETTINGS)})
    monkeypatch.setattr(activity_engine.core, "save_cfg", lambda cfg: None)
    with pytest.raises(ValueError, match="sample_interval_s"):
        activity_engine.update_settings({"sample_interval_s": 20})
    with pytest.raises(ValueError, match="semantic_context"):
        activity_engine.update_settings({"semantic_context": "true"})


def test_transition_time_window_wraps_across_midnight(monkeypatch):
    now = datetime.now().astimezone().replace(hour=0, minute=30, second=0, microsecond=0).timestamp()
    observed = {}
    monkeypatch.setattr(activity_engine.core, "db", lambda sql, args=(), many=False: observed.update(sql=sql, args=args) or [])
    monkeypatch.setattr(activity_engine, "_settings", lambda: dict(activity_engine.DEFAULT_SETTINGS))
    activity_engine._suggestions("app-key", now)
    assert "MIN(ABS(t.hour_local-?),24-ABS(t.hour_local-?))<=2" in observed["sql"]
    assert observed["args"][2] == observed["args"][3]
