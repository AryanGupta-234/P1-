import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from sentinel import core, collectors, inventory, ai, server, winutil


def isolated_core_db(monkeypatch):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript("""
        CREATE TABLE settings(setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, revision INTEGER NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE config_history(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL, changed_keys TEXT NOT NULL);
        CREATE TABLE runtime_snapshots(snapshot_key TEXT PRIMARY KEY, collected_at REAL NOT NULL, payload_json TEXT NOT NULL, sha256 TEXT NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE ai_usage_history(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, model TEXT, task TEXT, succeeded INTEGER NOT NULL, duration_s REAL, prompt_tokens INTEGER, output_tokens INTEGER, error TEXT);
    """)
    monkeypatch.setattr(core, "_db", connection)
    monkeypatch.setattr(core, "_db_lock", threading.Lock())
    return connection


def test_windows_system_command_path_takes_priority_over_path_hijack(monkeypatch):
    monkeypatch.setattr(winutil, "_system_candidates", lambda name: ["C:\\Windows\\System32\\powershell.exe"])
    monkeypatch.setattr(winutil.os.path, "isfile", lambda path: path.startswith("C:\\Windows"))
    monkeypatch.setattr(winutil.shutil, "which", lambda name: "C:\\Users\\Public\\powershell.exe")
    assert winutil.resolve_command("powershell.exe") == "C:\\Windows\\System32\\powershell.exe"


def test_config_history_records_nested_setting_changes(tmp_path, monkeypatch):
    connection = isolated_core_db(monkeypatch)
    monkeypatch.setattr(core, "CFG_PATH", str(tmp_path / "config.json"))
    core.save_cfg({"profile": {"sensors": {"processes": True}}, "autopilot": {"wpr_trace": False}})
    core.save_cfg({"profile": {"sensors": {"processes": False}}, "autopilot": {"wpr_trace": False}})
    row = connection.execute("SELECT revision, changed_keys FROM config_history ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == 2
    assert "profile.sensors.processes" in json.loads(row[1])


def test_save_cfg_does_not_create_a_revision_when_values_are_unchanged(tmp_path, monkeypatch):
    connection = isolated_core_db(monkeypatch)
    monkeypatch.setattr(core, "CFG_PATH", str(tmp_path / "config.json"))
    cfg = {"profile": {"sensors": {"processes": True}}, "cloud": {"key": ""}}
    core.save_cfg(cfg)
    core.save_cfg(cfg)
    assert connection.execute("SELECT COUNT(*) FROM config_history").fetchone()[0] == 1
    assert connection.execute("SELECT revision FROM settings WHERE setting_key='config'").fetchone()[0] == 1


def test_cloud_key_is_protected_before_storage_on_windows(monkeypatch):
    monkeypatch.setattr(core, "IS_WIN", True)
    monkeypatch.setattr(core, "_dpapi_transform", lambda raw, protect: (b"cipher:" + raw) if protect else raw.removeprefix(b"cipher:"))
    original = {"cloud": {"enabled": True, "key": "secret-token"}}
    stored = core._config_for_storage(original)
    assert stored["cloud"]["key"].startswith(core._DPAPI_PREFIX)
    assert "secret-token" not in json.dumps(stored)
    restored = core._config_from_storage(stored)
    assert restored["cloud"]["key"] == "secret-token"


def test_cloud_key_is_protected_in_json_and_sqlite_settings(tmp_path, monkeypatch):
    connection = isolated_core_db(monkeypatch)
    monkeypatch.setattr(core, "IS_WIN", True)
    monkeypatch.setattr(core, "CFG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(core, "_dpapi_transform", lambda raw, protect: b"cipher:" + raw if protect else raw.removeprefix(b"cipher:"))
    cfg = {"cloud": {"enabled": True, "key": "secret-token"}, "profile": {"sensors": {"processes": True}}}
    core.save_cfg(cfg)
    disk = (tmp_path / "config.json").read_text(encoding="utf-8")
    stored = connection.execute("SELECT value_json FROM settings WHERE setting_key='config'").fetchone()[0]
    assert "secret-token" not in disk
    assert "secret-token" not in stored
    assert core._config_from_storage(json.loads(stored))["cloud"]["key"] == "secret-token"


def test_cloud_key_persistence_fails_closed_when_dpapi_fails(monkeypatch):
    monkeypatch.setattr(core, "IS_WIN", True)
    def fail(*args, **kwargs): raise OSError("DPAPI unavailable")
    monkeypatch.setattr(core, "_dpapi_transform", fail)
    stored = core._config_for_storage({"cloud": {"key": "secret-token"}})
    assert stored["cloud"]["key"] == ""
    assert "secret-token" not in json.dumps(stored)


def test_profile_rejects_truthy_string_instead_of_coercing(monkeypatch):
    monkeypatch.setattr(core, "CFG", {"profile": core.get_profile()})
    monkeypatch.setattr(core, "save_cfg", lambda *_: None)
    with pytest.raises(ValueError, match="true or false"):
        core.set_profile({"sensors": {"processes": "false"}})
    changed = core.set_profile({"sensors": {"processes": False}})
    assert "sensors.processes=False" in changed


def test_process_close_review_requires_exact_visible_interactive_instance():
    row = {"pid": 4321, "create_time": 123.456, "exe": "/opt/test-app.exe",
           "session_id": 1, "visible_windows": 1, "onscreen_windows": 1, "path_state": "present"}
    assert server.find_reviewable_process(4321, 123.456, "/opt/test-app.exe", [row]) is row
    for change in ({"session_id": 0}, {"visible_windows": 0}, {"onscreen_windows": 0}, {"path_state": "inaccessible"}):
        candidate = {**row, **change}
        assert server.find_reviewable_process(4321, 123.456, "/opt/test-app.exe", [candidate]) is None
    assert server.find_reviewable_process(4321, 123.999, "/opt/test-app.exe", [row]) is None


def test_wpr_status_is_not_guessed_when_output_is_unrecognized():
    active = collectors.classify_wpr_status(0, "Recording is in progress")
    idle = collectors.classify_wpr_status(0, "WPR recording is not in progress")
    unknown = collectors.classify_wpr_status(0, "Windows Performance Recorder diagnostic output")
    negated = collectors.classify_wpr_status(0, "A recording profile is not running")
    assert active["recording"] is True and active["state"] == "recording"
    assert idle["recording"] is False and idle["state"] == "idle"
    assert negated["recording"] is False and negated["state"] == "idle"
    assert unknown["recording"] is None and unknown["state"] == "unknown"


def test_sensor_matrix_exposes_stale_and_error_states(monkeypatch):
    now = __import__("time").time()
    monkeypatch.setattr(server, "HEART", {
        "fresh": {"every": 1, "last": now, "runs": 10, "note": "ok", "err": ""},
        "stale": {"every": 1, "last": now - 100, "runs": 2, "note": "", "err": ""},
        "failed": {"every": 1, "last": now, "runs": 3, "note": "", "err": "access denied"},
        "disabled": {"every": 0, "last": 0, "runs": 0, "note": "not available", "err": ""},
    })
    matrix = server.sensor_matrix()
    by_name = {item["name"]: item["state"] for item in matrix["rows"]}
    assert by_name == {"disabled": "unavailable", "failed": "degraded", "fresh": "healthy", "stale": "stale"}


def test_inventory_posture_does_not_call_missing_sources_healthy(monkeypatch):
    monkeypatch.setattr(inventory, "_posted", set())
    monkeypatch.setattr(inventory, "insight", lambda *a, **k: None)
    data = {"health": {}, "security": {}, "volumes": [], "posture": []}
    inventory._posture(data)
    assert data["posture_summary"]["status"] == "incomplete"
    assert "defender" in data["posture_summary"]["unknown_sources"]


def test_service_reader_recovers_when_scm_iteration_raises_winerror2(monkeypatch):
    monkeypatch.setattr(collectors, "IS_WIN", True)

    class Service:
        def __init__(self, name): self._name = name
        def name(self): return self._name
        def display_name(self): return self._name + " display"
        def status(self): return "running"
        def start_type(self): return "auto"
        def pid(self): return 100
        def binpath(self): return "C:\\Windows\\system32\\svchost.exe"
        def username(self): return "LocalSystem"
        def description(self): return "test"

    def broken_iterator():
        yield Service("svc-one")
        raise FileNotFoundError(2, "The system cannot find the file specified", "(or service no longer exists)")

    monkeypatch.setattr(collectors.psutil, "win_service_iter", lambda: broken_iterator(), raising=False)
    fake_payload = {"count": 2, "services": [
        {"name": "svc-one", "display": "svc-one display", "state": "running", "start": "auto", "pid": 100},
        {"name": "svc-two", "display": "svc-two display", "state": "stopped", "start": "manual", "pid": 0},
    ]}
    import sentinel.winutil
    monkeypatch.setattr(sentinel.winutil, "powershell", lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(fake_payload), stderr=""))
    rows, errors = collectors._read_services()
    names = {row["name"] for row in rows}
    assert {"svc-one", "svc-two"}.issubset(names)
    assert any(item["service"] == "<psutil-fallback>" and item.get("recovered") for item in errors)
    assert all(item.get("recovered") for item in errors)


def test_latest_runtime_snapshots_are_keyed_and_integrity_stamped(monkeypatch):
    connection = isolated_core_db(monkeypatch)
    one = core.persist_snapshot("inventory.latest", {"apps": 12})
    two = core.persist_snapshot("inventory.latest", {"apps": 13})
    row = connection.execute("SELECT payload_json,sha256 FROM runtime_snapshots WHERE snapshot_key='inventory.latest'").fetchone()
    assert json.loads(row[0]) == {"apps": 13}
    assert row[1] == two["sha256"] != one["sha256"]
    assert len(core.runtime_snapshot_info()) == 1


def test_ai_inference_usage_is_written_to_sqlite(monkeypatch):
    connection = isolated_core_db(monkeypatch)
    monkeypatch.setattr(ai, "local_ok", lambda model: True)
    monkeypatch.setattr(ai, "_http", lambda *a, **k: {"response": "triage complete", "prompt_eval_count": 11,
        "eval_count": 4, "total_duration": 2_000_000_000})
    result = ai.gen("qwen-local", "test prompt", "test system", slot="fast")
    assert result == "triage complete"
    row = connection.execute("SELECT model,task,succeeded,prompt_tokens,output_tokens FROM ai_usage_history").fetchone()
    assert row == ("qwen-local", "fast", 1, 11, 4)
    assert ai.STATE["ai"]["usage"]["successes"] >= 1


def test_loopback_ollama_url_validation_rejects_remote_and_url_injection():
    assert core.valid_local_ollama_url("http://127.0.0.1:11434")
    assert core.valid_local_ollama_url("http://localhost:11434/")
    for value in (
        "https://example.com", "http://127.0.0.1:11434/api/tags",
        "http://user:pass@127.0.0.1:11434", "http://127.0.0.1:11434/?redirect=https://example.com",
        "http://127.0.0.1:99999", "file:///tmp/ollama",
    ):
        assert not core.valid_local_ollama_url(value), value


def test_local_ai_transport_rejects_non_loopback_before_network(monkeypatch):
    monkeypatch.setitem(ai.CFG, "ollama_url", "https://example.com")
    with pytest.raises(RuntimeError, match="loopback"):
        ai._http("/api/tags", timeout=1)


def test_failed_wpr_status_never_claims_trace_is_active_or_idle():
    result = collectors.classify_wpr_status(5, "Recording is in progress")
    assert result["available"] is False
    assert result["recording"] is None
    assert result["state"] == "unknown"


def test_inventory_preserves_component_security_health_for_posture(monkeypatch):
    monkeypatch.setattr(inventory, "IS_WIN", True)
    monkeypatch.setattr(inventory, "INV", {"ts": 0, "health": {}})
    monkeypatch.setattr(inventory, "_volumes", lambda: [])
    monkeypatch.setattr(inventory, "_ifaces", lambda: [])
    monkeypatch.setattr(inventory, "_services", lambda: [])
    monkeypatch.setattr(inventory, "_startup", lambda: [])
    monkeypatch.setattr(core, "persist_snapshot", lambda *a, **k: {})
    health = {key: {"ok": True} for key in (
        "apps", "tasks", "drivers", "platform", "security", "defender",
        "firewall", "secure_boot", "bitlocker", "physical")}
    payload = {"health": health, "apps": [], "tasks": [], "drivers": [],
        "platform": {"host": "test"}, "security": {"defender_rt": True,
        "firewall": [{"name": "Domain", "on": True}], "secure_boot": True,
        "bitlocker": []}, "physical": []}
    monkeypatch.setattr(inventory, "_ps", lambda *a, **k: payload)
    result = inventory.scan()
    assert result["health"]["defender"]["ok"] is True
    assert result["health"]["firewall"]["ok"] is True
    assert result["health"]["secure_boot"]["ok"] is True
    assert result["posture_summary"]["status"] == "clear"
    assert result["posture_summary"]["unknown_sources"] == []


def test_process_presence_never_equates_session_with_physical_visibility():
    assert collectors.classify_process_presence(0, 1, 1) == "session 0 / service or system"
    assert collectors.classify_process_presence(1, 1, 1) == "visible on physical monitor"
    assert collectors.classify_process_presence(1, 1, 0, cloaked=1) == "interactive session / DWM-cloaked window"
    assert collectors.classify_process_presence(1, 1, 0) == "interactive session / visible but off-monitor"
    assert collectors.classify_process_presence(1, 0, 0) == "interactive session / no visible window"


def test_demo_inventory_has_explicit_synthetic_health_and_posture(monkeypatch):
    monkeypatch.setattr(inventory, "IS_WIN", False)
    monkeypatch.setattr(inventory, "INV", {"ts": 0, "health": {}})
    monkeypatch.setattr(inventory, "_volumes", lambda: [])
    monkeypatch.setattr(inventory, "_ifaces", lambda: [])
    monkeypatch.setattr(inventory, "_services", lambda: [])
    monkeypatch.setattr(inventory, "_startup", lambda: [])
    monkeypatch.setattr(inventory, "insight", lambda *a, **k: None)
    monkeypatch.setattr(core, "persist_snapshot", lambda *a, **k: {})
    data = inventory.scan()
    assert data["ts"] > 0
    assert data["health"]["apps"]["mode"] == "synthetic demo data"
    assert data["posture_summary"]["unknown_sources"] == []
    assert len(data["apps"]) > 0
    assert len(data["services"]) > 0


def test_demo_process_rows_are_counted_and_explicitly_synthetic():
    rows = collectors._build_demo_process_rows(["chrome.exe", "explorer.exe", "dwm.exe"])
    assert len(rows) == 3
    assert len({(row["pid"], row["create_time"]) for row in rows}) == 3
    assert all(row["path_state"] == "synthetic demo (no host path)" for row in rows)
    assert all("synthetic demo" in row["app_kind"] for row in rows)
    assert all(row["session_id"] is None and row["onscreen_windows"] == 0 for row in rows)


def test_prune_archives_old_metrics_and_never_deletes_events(monkeypatch):
    connection = isolated_core_db(monkeypatch)
    connection.executescript("""
        CREATE TABLE metrics(ts REAL, k TEXT, v REAL);
        CREATE TABLE events(id INTEGER PRIMARY KEY, ts REAL, level TEXT, src TEXT, msg TEXT, data TEXT);
        CREATE TABLE metrics_hourly_archive(hour_epoch INTEGER NOT NULL,k TEXT NOT NULL,sample_count INTEGER NOT NULL,
            sum_v REAL NOT NULL,min_v REAL NOT NULL,max_v REAL NOT NULL,PRIMARY KEY(hour_epoch,k));
    """)
    import time
    now = time.time()
    old = now - 3 * 86400
    connection.executemany("INSERT INTO metrics(ts,k,v) VALUES(?,?,?)", [
        (old, "dpc", 1.0), (old + 5, "dpc", 3.0), (old + 8, "dpc", 2.0)
    ])
    connection.execute("INSERT INTO events(ts,level,src,msg,data) VALUES(?,?,?,?,?)", (old, "info", "test", "retain me", "{}"))
    monkeypatch.setattr(core, "CFG", {"retention_days": 1})
    result = core.prune()
    archive = connection.execute("SELECT sample_count,sum_v,min_v,max_v FROM metrics_hourly_archive WHERE k='dpc'").fetchone()
    assert result["archived_rows"] == 3
    assert archive == (3, 6.0, 1.0, 3.0)
    assert connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0
    assert connection.execute("SELECT msg FROM events").fetchone()[0] == "retain me"


def test_permanent_history_tables_are_not_trimmed_in_ai_module():
    from pathlib import Path
    source = Path(ai.__file__).read_text(encoding="utf-8")
    assert "DELETE FROM ai_usage_history" not in source
    assert "DELETE FROM ai_messages" not in source


def test_process_inventory_keeps_access_denied_placeholder(monkeypatch):
    # The scan's access-denied branch must preserve a countable, explicitly unknown row.
    import inspect
    source = inspect.getsource(collectors.scan_processes)
    assert '"<access denied>"' in source
    assert 'STATE["proc_inaccessible"] = inaccessible' in source


def test_process_rows_deduplicate_by_pid_and_creation_time_only():
    rows = [
        {"pid": 10, "create_time": 100.0, "name": "<access denied>", "exe": "", "path_state": "access_denied"},
        {"pid": 10, "create_time": 100.0, "name": "app.exe", "exe": "C:\\Apps\\app.exe", "path_state": "present"},
        {"pid": 10, "create_time": 101.0, "name": "app.exe", "exe": "C:\\Apps\\app.exe", "path_state": "present"},
        {"pid": 11, "create_time": 100.0, "name": "app.exe", "exe": "C:\\Apps\\app.exe", "path_state": "present"},
    ]
    result = collectors.dedupe_process_rows(rows)
    assert len(result) == 3
    assert next(row for row in result if row["pid"] == 10 and row["create_time"] == 100.0)["name"] == "app.exe"