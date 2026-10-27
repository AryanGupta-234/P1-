import json
import os
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from sentinel import core, collectors, inventory, ai, ai_engine, server, winutil

import agent


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
    # This test covers usage persistence, not the runner's live host-load policy.
    monkeypatch.setattr(ai_engine, "inference_allowed", lambda *a, **k: (True, "isolated test"))
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

def _fake_agent_process():
    class FakeProcess:
        def exe(self):
            return r"C:\Python312\python.exe"
        def username(self):
            return "TEST-PC\\Aryan"
        def memory_info(self):
            return SimpleNamespace(rss=64 * 1024 * 1024)
        def memory_percent(self):
            return 0.4
        def cpu_percent(self, interval=None):
            assert interval is None
            return 120.0
        def num_threads(self):
            return 18
        def num_handles(self):
            return 77
        def create_time(self):
            return time.time() - 120
        def io_counters(self):
            return SimpleNamespace(read_bytes=1024**2 * 3, write_bytes=1024**2 * 5)
        def is_running(self):
            return True
        def status(self):
            return "running"
    return FakeProcess()


def test_agent_runtime_separates_agent_cpu_ram_from_host_resources(monkeypatch):
    process = _fake_agent_process()
    monkeypatch.setattr(server, "_AGENT_PROCESS", process)
    monkeypatch.setattr(server.psutil, "cpu_count", lambda logical=True: 12)
    monkeypatch.setattr(server.psutil, "cpu_percent", lambda interval=None: 42.4)
    monkeypatch.setattr(
        server.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            total=16 * 1024**3,
            used=10 * 1024**3,
            available=6 * 1024**3,
            percent=62.5,
        ),
    )
    monkeypatch.setattr(core, "IS_WIN", True)
    monkeypatch.setattr(collectors, "_session_id", lambda _pid: 3)
    monkeypatch.setattr(
        server.threading,
        "enumerate",
        lambda: [
            SimpleNamespace(name="MainThread", is_alive=lambda: True, daemon=False),
            SimpleNamespace(name="process inventory", is_alive=lambda: True, daemon=True),
            SimpleNamespace(name="brain", is_alive=lambda: True, daemon=True),
            SimpleNamespace(name="stopped worker", is_alive=lambda: False, daemon=True),
        ],
    )
    monkeypatch.setattr(
        core,
        "db",
        lambda _sql, _args=(): [(7, time.time() - 120, "windows-interactive", None)],
    )

    runtime = server.agent_runtime()

    assert runtime["state"] == "running"
    assert runtime["rss_mb"] == 64.0
    assert runtime["memory_percent"] == 0.4
    assert runtime["cpu_one_core_percent"] == 120.0
    assert runtime["logical_processors"] == 12
    assert runtime["cpu_percent"] == 10.0
    assert runtime["host_cpu_percent"] == 42.4
    assert runtime["host_memory"] == {
        "total_mb": 16384,
        "used_mb": 10240,
        "available_mb": 6144,
        "percent": 62.5,
    }
    assert runtime["threads"] == 18
    assert runtime["handles"] == 77
    assert runtime["io_read_bytes"] == 3 * 1024**2
    assert runtime["io_write_bytes"] == 5 * 1024**2
    assert {item["name"] for item in runtime["worker_threads"]} == {
        "process inventory", "brain", "stopped worker"
    }
    assert runtime["run"]["id"] == 7
    assert runtime["session_id"] == 3
    assert runtime["desktop_access_expected"] is True


def test_runtime_snapshot_persistence_writes_integrity_stamped_row(monkeypatch):
    connection = isolated_core_db(monkeypatch)

    result = core.persist_snapshot("kernel.latest", {"source": "test", "samples": 12})

    row = connection.execute(
        "SELECT payload_json,sha256 FROM runtime_snapshots WHERE snapshot_key=?",
        ("kernel.latest",),
    ).fetchone()
    assert row is not None
    assert json.loads(row[0]) == {"samples": 12, "source": "test"}
    assert result["sha256"] == row[1]
    assert result["bytes"] == len(row[0].encode("utf-8"))


def test_kernel_snapshot_payload_includes_live_metrics(monkeypatch):
    from sentinel import collectors

    captured = {}
    monkeypatch.setattr(collectors.time, "monotonic", lambda: 45.0)
    monkeypatch.setattr(collectors.time, "time", lambda: 2026.0)
    monkeypatch.setitem(collectors.LIVE, "dpc", 1.25)
    monkeypatch.setitem(collectors.LIVE, "pagesin", 3.0)
    monkeypatch.setattr(
        collectors.core,
        "persist_snapshot",
        lambda key, payload: captured.update({"key": key, "payload": payload}),
    )

    last_attempt = collectors._persist_kernel_snapshot({"samples": 12}, 0.0)

    assert last_attempt == 45.0
    assert captured["key"] == "kernel.latest"
    assert captured["payload"]["values"]["dpc"] == 1.25
    assert captured["payload"]["values"]["pagesin"] == 3.0
    assert captured["payload"]["pdh"]["samples"] == 12


def test_kernel_snapshot_failure_includes_exception_detail_and_is_throttled(monkeypatch):
    from sentinel import collectors

    clock = {"value": 100.0}
    logs = []

    def fail_snapshot(*_args, **_kwargs):
        raise NameError("missing snapshot serializer binding")

    monkeypatch.setattr(collectors.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(collectors.time, "time", lambda: 2000.0 + clock["value"])
    monkeypatch.setattr(collectors.core, "persist_snapshot", fail_snapshot)
    monkeypatch.setattr(collectors, "log", lambda *args, **kwargs: logs.append((args, kwargs)))

    last_attempt = collectors._persist_kernel_snapshot({"samples": 1}, 0.0)
    assert last_attempt == 100.0
    assert len(logs) == 1
    assert "NameError: missing snapshot serializer binding" in logs[0][0][1]

    clock["value"] = 110.0
    assert collectors._persist_kernel_snapshot({"samples": 2}, last_attempt) == last_attempt
    assert len(logs) == 1

    clock["value"] = 131.0
    assert collectors._persist_kernel_snapshot({"samples": 3}, last_attempt) == 131.0
    assert len(logs) == 2


def test_environment_evidence_cards_have_non_overlapping_responsive_layout():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]
    html = (root / "ui" / "index.html").read_text(encoding="utf-8")
    css = (root / "ui" / "app.css").read_text(encoding="utf-8")
    script = (root / "ui" / "app.js").read_text(encoding="utf-8")
    ids = re.findall(r'id="([^"]+)"', html)

    assert len(ids) == len(set(ids)), "dashboard HTML must not contain duplicate element IDs"
    assert 'id="adv-cpu-threshold-note"' in html
    assert 'id="adv-live-metrics"' in html
    assert ".ix-state-row{\n  display:grid;" in css
    assert ".ix-state-row>.ix-evidence{\n  grid-column:1/-1;" in css
    assert "aria-expanded" in script
    assert "renderAdvLiveMetrics" in script


def test_agent_runtime_lightweight_stream_skips_worker_and_disk_io_enumeration(monkeypatch):
    process = _fake_agent_process()
    monkeypatch.setattr(server, "_AGENT_PROCESS", process)
    monkeypatch.setattr(server.psutil, "cpu_count", lambda logical=True: 4)
    monkeypatch.setattr(server.psutil, "cpu_percent", lambda interval=None: 5.0)
    monkeypatch.setattr(
        server.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024**3, used=3 * 1024**3,
                                available=5 * 1024**3, percent=37.5),
    )
    monkeypatch.setattr(core, "IS_WIN", False)
    monkeypatch.setattr(collectors, "_session_id", lambda _pid: None)
    monkeypatch.setattr(
        core,
        "db",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lightweight snapshot must not query run history")),
    )

    runtime = server.agent_runtime(include_threads=False, include_io=False, include_run=False)

    assert runtime["worker_threads"] is None
    assert runtime["io_read_bytes"] is None
    assert runtime["io_write_bytes"] is None
    assert runtime["run"] is None
    assert runtime["cpu_percent"] == 30.0


def test_agent_run_history_exposes_active_and_completed_runs(monkeypatch):
    now = time.time()
    monkeypatch.setattr(
        core,
        "db",
        lambda sql, args=(): [
            (9, now - 20, None, 4321, r"C:\Python\pythonw.exe", "windows-interactive", None),
            (8, now - 200, now - 100, 3210, r"C:\Python\python.exe", "windows-interactive", "normal shutdown"),
        ],
    )

    runs = server.agent_run_history(20)

    assert len(runs) == 2
    assert runs[0]["active"] is True
    assert runs[0]["id"] == 9
    assert runs[1]["active"] is False
    assert runs[1]["duration_s"] == 100.0
    assert runs[1]["exit_reason"] == "normal shutdown"


def test_agent_shutdown_request_uses_a_separate_thread(monkeypatch):
    state = {"called": False}

    class FakeServer:
        def shutdown(self):
            state["called"] = True

    class FakeThread:
        def __init__(self, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon
        def start(self):
            self.target()

    monkeypatch.setattr(server, "_HTTP_SERVER", FakeServer())
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    assert server.request_shutdown() is True
    assert state["called"] is True


def test_installer_uses_immutable_version_folders_and_preserves_programdata():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    installer = (root / "install.bat").read_text(encoding="utf-8")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()

    stop_at = installer.index('%PY% "%SRC%\\agent.py" stop')
    copy_at = installer.index("robocopy ")
    environment_at = installer.index(" -m venv ")
    dependencies_at = installer.index("pip install --disable-pip-version-check")
    registration_at = installer.index('"%VERSION_DIR%\\agent.py" install')
    assert stop_at < copy_at < environment_at < dependencies_at < registration_at
    assert 'set /p "VERSION="<"%VERSION_FILE%"' in installer
    assert "%VERSIONS%\\%VERSION%" in installer
    assert "%STAGING_DIR%" in installer
    assert 'move "%STAGING_DIR%" "%VERSION_DIR%"' in installer
    assert 'set "FRESH_VERSION=0"' in installer
    assert 'set "FRESH_VERSION=1"' in installer
    assert 'set "VENV_PY=%VERSION_DIR%\\.venv\\Scripts\\python.exe"' in installer
    assert '%PY% -m venv "%VERSION_DIR%\\.venv"' in installer
    assert installer.index('"%VENV_PY%" -m pip install') < installer.index('"%VENV_PY%" "%VERSION_DIR%\\agent.py" install')
    assert ":fresh_environment_failed" in installer
    assert 'if "%FRESH_VERSION%"=="1"' in installer
    assert 'if exist "%VERSION_DIR%"' in installer
    assert "findstr /R /X /C:" in installer
    assert "/E /R:2 /W:2" in installer
    assert "/MIR" not in installer
    assert ".venv\\Scripts\\python.exe" in installer
    assert "active-version.txt" in installer
    assert "INSTALLATION COMPLETE" in installer
    assert "Start Menu" in installer
    assert "%ProgramData%\\Sentinel" in installer
    assert "setlocal EnableExtensions DisableDelayedExpansion" in installer


def test_release_marker_and_runtime_report_a_semantic_version():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert agent.APP_VERSION == version
    assert agent.APP_VERSION_DIR.endswith(os.path.join("versions", version))


def test_install_integration_verifies_desktop_and_all_users_shortcuts(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    python_exe = scripts / "python.exe"
    pythonw_exe = scripts / "pythonw.exe"
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe.write_text("", encoding="utf-8")
    release_dir = tmp_path / "versions" / agent.APP_VERSION
    release_scripts = release_dir / ".venv" / "Scripts"
    release_scripts.mkdir(parents=True)
    (release_scripts / "python.exe").write_text("", encoding="utf-8")
    (release_scripts / "pythonw.exe").write_text("", encoding="utf-8")
    (release_dir / "agent.py").write_text("", encoding="utf-8")
    (release_dir / "ui").mkdir()
    (release_dir / "ui" / "index.html").write_text("", encoding="utf-8")
    monkeypatch.setattr(agent, "APP_VERSION_DIR", str(release_dir))
    for key in ("SENTINEL_TASK", "SENTINEL_PYTHONW", "SENTINEL_SCRIPT",
                "SENTINEL_WORKDIR", "SENTINEL_STORE", "SENTINEL_VERSION"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr(agent, "IS_WIN", True)
    monkeypatch.setattr(agent.sys, "executable", str(python_exe))
    captured = {}

    def capture_script(script):
        captured["script"] = script
        return SimpleNamespace(returncode=1, stdout="", stderr="controlled failure")

    monkeypatch.setattr(agent, "pw", capture_script)

    assert agent.install() == 1
    script = captured["script"]
    assert "Win32_ComputerSystem" in script
    assert "User Shell Folders" in script
    assert "Join-Path $env:ProgramData 'Microsoft\\Windows\\Start Menu\\Programs'" in script
    assert "Join-Path $commonPrograms 'SENTINEL'" in script
    assert "(Join-Path $desktop 'SENTINEL.lnk')" in script
    assert "(Join-Path $userPrograms 'SENTINEL.lnk')" in script
    assert "(Join-Path $commonPrograms 'SENTINEL.lnk')" in script
    assert "(Join-Path $commonStartMenuGroup 'SENTINEL.lnk')" in script
    assert "Test-Path -LiteralPath $item.Path -PathType Leaf" in script
    assert "$check.TargetPath -ne $pythonw" in script
    assert "RunLevel Limited" in script
    assert "standard-user interactive Windows agent" in script
    assert "INSTALL_DESKTOP=" in script
    assert "INSTALL_START_MENU=" in script

def test_desktop_opener_uses_verified_standard_user_agent_without_spawning_another(monkeypatch):
    called = {"launch": 0, "start": 0}
    runtime = {
        "is_elevated": False, "desktop_access_expected": True, "session_id": 7,
        "username": r"TEST-PC\tester", "version": agent.APP_VERSION,
        "executable": os.path.join(agent.APP_VERSION_DIR, ".venv", "Scripts", "python.exe"),
        "python_prefix": os.path.join(agent.APP_VERSION_DIR, ".venv"),
    }
    monkeypatch.setattr(agent, "IS_WIN", True)
    monkeypatch.setattr(agent, "_current_windows_session_id", lambda: 7)
    monkeypatch.setattr(agent, "_current_windows_username", lambda: r"TEST-PC\tester")
    monkeypatch.setattr(agent, "_running_agent_runtime", lambda: runtime)
    monkeypatch.setattr(agent, "_wait_for_agent", lambda _timeout: True)
    monkeypatch.setattr(agent, "_launch_hud", lambda: called.__setitem__("launch", called["launch"] + 1) or True)
    monkeypatch.setattr(agent, "_start_agent_background", lambda: called.__setitem__("start", called["start"] + 1))

    assert agent.open_app() == 0
    assert called == {"launch": 1, "start": 0}


def test_desktop_opener_starts_agent_when_authenticated_api_is_not_ready(monkeypatch):
    readiness = iter([False, True])
    called = {"launch": 0, "start": 0}
    monkeypatch.setattr(agent, "IS_WIN", False)
    monkeypatch.setattr(agent, "_wait_for_agent", lambda _timeout: next(readiness))
    monkeypatch.setattr(agent, "_launch_hud", lambda: called.__setitem__("launch", called["launch"] + 1) or True)
    monkeypatch.setattr(agent, "_start_agent_background", lambda: called.__setitem__("start", called["start"] + 1))

    assert agent.open_app() == 0
    assert called == {"launch": 1, "start": 1}


def test_upgrade_stop_checks_task_even_when_local_port_is_not_listening(monkeypatch):
    called = []
    monkeypatch.setattr(agent, "port_busy", lambda: False)
    monkeypatch.setattr(agent, "_stop_legacy_agent", lambda: called.append("task-stop") or True)

    assert agent.stop_agent() == 0
    assert called == ["task-stop"]




def test_admin_guard_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(agent, "IS_WIN", False)
    assert agent._ensure_admin() is None


def test_admin_guard_relaunches_with_runas_and_forwards_all_arguments(monkeypatch):
    shell_execute = __import__("unittest.mock", fromlist=["Mock"]).Mock(return_value=42)
    shell32 = SimpleNamespace(IsUserAnAdmin=lambda: False, ShellExecuteW=shell_execute)
    fake_ctypes = SimpleNamespace(
        c_void_p=agent.ctypes.c_void_p,
        windll=SimpleNamespace(
            shell32=shell32,
            user32=SimpleNamespace(MessageBoxW=lambda *_args: None),
        )
    )
    monkeypatch.setattr(agent, "ctypes", fake_ctypes)
    monkeypatch.setattr(agent, "IS_WIN", True)
    monkeypatch.setattr(agent.sys, "executable", r"C:\Python312\python.exe")
    monkeypatch.setattr(agent.sys, "argv", [agent.__file__, "open", "folder with spaces"])

    assert agent._ensure_admin() == 0
    shell_execute.assert_called_once()
    call = shell_execute.call_args.args
    assert call[1] == "runas"
    assert call[2] == r"C:\Python312\python.exe"
    assert call[3] == agent.subprocess.list2cmdline(
        [agent.os.path.abspath(agent.__file__), "open", "folder with spaces"]
    )
    assert call[4] == agent.HERE


def test_admin_guard_fails_closed_when_uac_is_cancelled(monkeypatch):
    from unittest.mock import Mock

    message_boxes = []
    shell_execute = Mock(return_value=5)
    fake_ctypes = SimpleNamespace(
        c_void_p=agent.ctypes.c_void_p,
        windll=SimpleNamespace(
            shell32=SimpleNamespace(IsUserAnAdmin=lambda: False, ShellExecuteW=shell_execute),
            user32=SimpleNamespace(MessageBoxW=lambda *args: message_boxes.append(args)),
        )
    )
    monkeypatch.setattr(agent, "ctypes", fake_ctypes)
    monkeypatch.setattr(agent, "IS_WIN", True)
    monkeypatch.setattr(agent.sys, "argv", [agent.__file__, "open"])
    monkeypatch.setattr(agent.sys, "stderr", None)

    assert agent._ensure_admin() == 1
    assert len(message_boxes) == 1
    assert "requires administrator permissions" in message_boxes[0][1]


def test_desktop_opener_replaces_elevated_agent_with_standard_user_runtime(monkeypatch):
    readiness = iter([True, True])
    runtimes = iter([
        {
            "is_elevated": True, "desktop_access_expected": True, "session_id": 7,
            "username": r"TEST-PC\tester", "version": agent.APP_VERSION,
        },
        {
            "is_elevated": False, "desktop_access_expected": True, "session_id": 7,
            "username": r"TEST-PC\tester", "version": agent.APP_VERSION,
            "python_prefix": os.path.join(agent.APP_VERSION_DIR, ".venv"),
        },
    ])
    calls = {"stop": 0, "start": 0, "launch": 0}
    monkeypatch.setattr(agent, "IS_WIN", True)
    monkeypatch.setattr(agent, "_current_windows_session_id", lambda: 7)
    monkeypatch.setattr(agent, "_current_windows_username", lambda: r"TEST-PC\tester")
    monkeypatch.setattr(agent, "_wait_for_agent", lambda _timeout: next(readiness))
    monkeypatch.setattr(agent, "_running_agent_runtime", lambda: next(runtimes))
    monkeypatch.setattr(agent, "stop_agent", lambda: calls.__setitem__("stop", calls["stop"] + 1) or 0)
    monkeypatch.setattr(agent, "pw", lambda _command: SimpleNamespace(returncode=1, stdout="", stderr=""))
    monkeypatch.setattr(agent, "_start_agent_background", lambda: calls.__setitem__("start", calls["start"] + 1))
    monkeypatch.setattr(agent, "_launch_hud", lambda: calls.__setitem__("launch", calls["launch"] + 1) or True)

    assert agent.open_app() == 0
    assert calls == {"stop": 1, "start": 1, "launch": 1}
