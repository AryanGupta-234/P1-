import json
import sqlite3
import time
from pathlib import Path

from sentinel import advanced, core


def memory_store(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    def execute(sql, args=()):
        cur = conn.execute(sql, args)
        rows = cur.fetchall() if sql.lstrip().lower().startswith("select") else []
        conn.commit()
        return rows

    monkeypatch.setattr(advanced, "db", execute)
    advanced._ensure_schema()
    conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY,ts REAL,level TEXT,src TEXT,msg TEXT,data TEXT)")
    conn.execute("CREATE TABLE actions(id INTEGER PRIMARY KEY,ts REAL,kind TEXT,state TEXT,result TEXT,args TEXT)")
    conn.commit()
    return conn


def test_risk_policy_has_six_advisory_specialists_and_dangerous_never_auto():
    assert len(advanced.SPECIALISTS) == 6
    assert advanced.risk_tier("etw_capture") == "safe"
    assert advanced.risk_tier("game_profile_apply") == "medium"
    assert advanced.risk_tier("pause_updater_service") == "medium"
    assert advanced.risk_tier("terminate_process") == "medium"
    close_preview = advanced.action_preview("terminate_process", {})
    assert close_preview["supported"] is False
    assert close_preview["automatic_allowed"] is False
    assert close_preview["undo_available"] is False
    for kind in ("standby_flush", "fan_control", "trim_bg", "flush_dns", "bg_priority"):
        assert advanced.risk_tier(kind) == "dangerous"
        preview = advanced.action_preview(kind, {})
        assert preview["supported"] is False
        assert preview["automatic_allowed"] is False
        assert preview["undo_available"] is False


def test_personal_baselines_use_welford_per_game_and_local_hour(monkeypatch):
    memory_store(monkeypatch)
    for i, value in enumerate((10.0, 12.0, 14.0, 16.0)):
        advanced._baseline_sample("valorant-win64-shipping.exe", 20, {"cpu": value}, 1000.0 + i)
    data = advanced._baseline_for("valorant-win64-shipping.exe", 20)
    assert data["cpu"]["samples"] == 4
    assert data["cpu"]["mean"] == 13.0
    assert round(data["cpu"]["stddev"], 5) == round((20.0 / 3.0) ** 0.5, 5)
    assert advanced._baseline_for("other-game.exe", 20) == {}
    assert advanced._baseline_for("valorant-win64-shipping.exe", 21) == {}


def test_correlation_includes_etw_thermal_and_recent_sentinel_actions(monkeypatch):
    conn = memory_store(monkeypatch)
    conn.execute("INSERT INTO events VALUES(1,95,'warn','process','process started','{}')")
    conn.execute("INSERT INTO etw_attribution(ts,trace_path,provider,event_name,pid,process_name,attribution,evidence_json) VALUES(?,?,?,?,?,?,?,?)",
                 (96, "trace.etl", "Kernel-Process", "ProcessStart", 123, "game.exe", "PID from ETW header", "{}"))
    conn.execute("INSERT INTO thermal_events(ts,sensor,event,value,threshold,detail) VALUES(?,?,?,?,?,?)",
                 (97, "gpu", "pre_throttle_warning", 83.0, 82.0, "warning"))
    conn.execute("INSERT INTO actions VALUES(1,98,'power_plan','done','changed','{}')")
    conn.commit()
    rows = advanced._correlate_window(90, 100)
    sources = {x["source"] for x in rows}
    assert {"process", "ETW", "thermal", "SENTINEL action"}.issubset(sources)
    assert all(any(word in x["relationship"] for word in ("caus", "temporal")) for x in rows)


def test_session_action_is_linked_only_to_active_game_session(monkeypatch):
    conn = memory_store(monkeypatch)
    conn.execute("INSERT INTO game_sessions(game_key,pid,create_time,started_at,before_json,status) VALUES('game.exe',123,1,1,'{}','active')")
    conn.commit()
    monkeypatch.setitem(advanced.STATE, "advanced", {"active_session_id": 1})
    assert advanced.link_action_to_session(55) is True
    row = conn.execute("SELECT session_id,action_id FROM session_actions").fetchone()
    assert tuple(row) == (1, 55)
    conn.execute("UPDATE game_sessions SET status='completed' WHERE id=1")
    conn.commit()
    assert advanced.link_action_to_session(56, 1) is False


def test_wifi_undo_preserves_a_policy_changed_after_sentinel(monkeypatch):
    # Do not overwrite a newer user-selected power scheme or AC policy.
    monkeypatch.setattr(advanced, "_wifi_power_setting", lambda: {"scheme": "new-scheme", "ac_index": 2})
    result = advanced._restore({"kind": "wifi_max_performance", "scheme": "old-scheme",
                                "subgroup": "group", "setting": "setting", "ac_index": 1,
                                "applied_ac_index": 0})
    assert "preserving user change" in result


def test_game_profile_undo_only_restores_fields_unchanged_since_apply(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.priority = 3
            self.affinity = [0, 1]
        def nice(self, value=None):
            if value is not None: self.priority = value
            return self.priority
        def cpu_affinity(self, value=None):
            if value is not None: self.affinity = list(value)
            return self.affinity
    proc = FakeProc()
    monkeypatch.setattr(advanced, "_process_identity", lambda args: (proc, {}))
    monkeypatch.setattr(advanced, "_get_process_default_cpu_sets", lambda pid: None)
    result = advanced._restore({"kind": "game_profile_apply", "pid": 123, "create_time": 1,
        "exe": "C:/Games/game.exe", "priority_class": 2, "cpu_affinity": [0, 1],
        "applied_priority_class": 3, "applied_cpu_affinity": [0, 1],
        "applied_process_state_captured": True, "default_cpu_sets": None,
        "background_processes": [], "timer_applied_ms": 0, "power_plan": None})
    assert proc.priority == 2
    assert proc.affinity == [0, 1]
    assert "restored eligible" in result


def test_closed_loop_measurement_keeps_original_pre_action_baseline(monkeypatch):
    conn = memory_store(monkeypatch)
    now = time.time()
    conn.execute("INSERT INTO action_journal(action_id,kind,risk,created_at,before_json,undo_json,undo_available) VALUES(1,'power_plan','medium',?,'{}','{}',1)", (now,))
    conn.execute("INSERT INTO tuner_experiments(action_id,metric,before_value,target_direction,started_at,outcome) VALUES(1,'dpc',50.0,'lower',?,'awaiting_approval')", (now,))
    conn.commit()
    monkeypatch.setattr(advanced, "_power_plan", lambda: "new-scheme")
    monkeypatch.setattr(advanced, "_metric_mean", lambda metric, seconds: (999.0, 99))
    advanced.mark_action_result(1, "High performance power plan activated", True)
    row = conn.execute("SELECT before_value,outcome,detail FROM tuner_experiments WHERE action_id=1").fetchone()
    assert row[0] == 50.0
    assert row[1] == "measuring"
    assert "pre-action baseline retained" in row[2]


def test_game_profile_prepare_requires_the_detected_active_game(monkeypatch):
    memory_store(monkeypatch)
    class FakeProc:
        pass
    monkeypatch.setattr(advanced, "IS_WIN", True)
    monkeypatch.setattr(advanced, "_process_identity", lambda args: (FakeProc(), {
        "pid": 321, "create_time": 100.0, "exe": "c:/games/game.exe",
        "name": "game.exe", "priority_class": 32, "cpu_affinity": [0, 1],
    }))
    monkeypatch.setattr(advanced, "_get_process_default_cpu_sets", lambda pid: [])
    monkeypatch.setitem(advanced.STATE, "game", None)
    try:
        advanced.prepare_action(88, "game_profile_apply", {
            "pid": 321, "create_time": 100.0, "exe": "c:/games/game.exe", "profile": {"priority": "normal"}
        })
    except RuntimeError as exc:
        assert "currently detected game process" in str(exc)
    else:
        raise AssertionError("game profile must not target an arbitrary process")


def test_game_profile_undo_after_game_exit_still_restores_global_power_state(monkeypatch):
    def missing_process(_args):
        import psutil
        raise psutil.NoSuchProcess(321)
    monkeypatch.setattr(advanced, "_process_identity", missing_process)
    monkeypatch.setattr(advanced, "_power_plan", lambda: "applied-scheme")
    run_calls = []
    class Result:
        returncode = 0
    def fake_run(args, timeout=15):
        run_calls.append(args)
        return Result()
    monkeypatch.setattr(advanced, "_run", fake_run)
    result = advanced._restore({"kind": "game_profile_apply", "pid": 321, "create_time": 100.0,
        "exe": "c:/games/game.exe", "default_cpu_sets": None, "applied_default_cpu_sets": None,
        "background_processes": [], "timer_applied_ms": 1, "power_plan": "previous-scheme",
        "applied_plan": "applied-scheme"})
    assert any("/setactive" in args for args in run_calls)
    assert "process has exited" in result
    assert "restored eligible" in result


def test_etw_preview_explains_missing_inbox_wpr(monkeypatch):
    monkeypatch.setattr(advanced, "IS_WIN", True)
    monkeypatch.setattr(advanced, "locate_wpr", lambda: None)
    monkeypatch.setattr(advanced.safeguard, "check_action", lambda *_args, **_kwargs: {"allowed": True, "code": "allowed", "reason": "test"})

    preview = advanced.action_preview("etw_capture", {"duration": 12})

    assert preview["supported"] is False
    assert any("wpr.exe" in warning.lower() for warning in preview["warnings"])
    assert all("Windows ADK" not in warning for warning in preview["warnings"])




def test_advanced_status_always_includes_live_metric_contract_without_game(monkeypatch):
    memory_store(monkeypatch)
    monkeypatch.setitem(advanced.STATE, "game", None)
    monkeypatch.setitem(advanced.STATE, "advanced", {})
    monkeypatch.setitem(advanced.STATE, "kernel", {})
    monkeypatch.setitem(advanced.STATE, "gpu", {})
    monkeypatch.setitem(advanced.STATE, "hardware_sensors", {"available": False})
    monkeypatch.setattr(advanced, "_check_network_evidence", lambda: {"supported": False, "reason": "insufficient samples"})
    monkeypatch.setattr(advanced, "_cpu_set_inventory", lambda: {"available": False, "reason": "test"})

    payload = advanced.status()

    assert payload["game"] is None
    assert "live_metrics" in payload
    assert {"cpu", "mem", "dpc", "irq", "pagesin", "dlat", "ping", "jitter"}.issubset(payload["live_metrics"])
    assert payload["sessions"] == []
    assert payload["action_journal"] == []
    assert payload["tuner_history"] == []


def test_etw_capture_dry_run_advertises_bounded_trace_undo():
    preview = advanced.action_preview("etw_capture", {"duration": 12})
    assert preview["risk"] == "safe"
    assert preview["automatic_allowed"] is True
    assert preview["undo_available"] is True
    assert "bounded" in " ".join(preview["changes"]).lower()


def test_interrupted_session_recovery_closes_sessions_and_clears_active_pointer(monkeypatch):
    conn = memory_store(monkeypatch)
    conn.execute("INSERT INTO game_sessions(game_key,started_at,before_json,status) VALUES('game.exe',1,'{}','active')")
    conn.commit()
    monkeypatch.setitem(advanced.STATE, "advanced", {"active_session_id": 1})
    def recover(session_id, ts):
        conn.execute("UPDATE game_sessions SET status='completed',ended_at=? WHERE id=?", (ts, session_id))
        return {"duration_seconds": 12}
    monkeypatch.setattr(advanced, "_end_game_session", recover)
    advanced._recover_interrupted_sessions()
    assert conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0] == "completed"
    assert "active_session_id" not in advanced.STATE["advanced"]


def test_restart_reuses_the_same_live_game_process_session(monkeypatch):
    conn = memory_store(monkeypatch)
    conn.execute("INSERT INTO game_sessions(game_key,pid,create_time,started_at,before_json,status) VALUES('game.exe',321,100,10,'{}','active')")
    conn.commit()
    class FakeProcess:
        def __init__(self, pid): self.pid = pid
        def create_time(self): return 100.0
        def name(self): return "game.exe"
        def exe(self): return "C:/Games/game.exe"
    monkeypatch.setattr(advanced.psutil, "Process", FakeProcess)
    monkeypatch.setitem(advanced.STATE, "advanced", {})
    monkeypatch.setitem(advanced.STATE, "game", None)
    monkeypatch.setattr(advanced, "_end_game_session", lambda *a: (_ for _ in ()).throw(AssertionError("must resume live game")))
    advanced._recover_interrupted_sessions()
    assert advanced.STATE["advanced"]["active_session_id"] == 1
    assert advanced.STATE["game"]["pid"] == 321
    assert advanced._LAST_GAME_ID == "game.exe:321:100.0"
    assert conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0] == "active"


def test_normal_shutdown_restores_the_active_session(monkeypatch):
    memory_store(monkeypatch)
    called = []
    monkeypatch.setitem(advanced.STATE, "advanced", {"active_session_id": 7})
    monkeypatch.setitem(advanced.STATE, "game", {"name": "game.exe"})
    monkeypatch.setattr(advanced, "_end_game_session", lambda sid, ts: called.append(sid) or {"duration_seconds": 10})
    monkeypatch.setattr(advanced, "_ETW_OWNED", False)
    monkeypatch.setattr(advanced, "_TIMER_REQUESTS", {})
    advanced.shutdown()
    assert called == [7]
    assert "active_session_id" not in advanced.STATE["advanced"]
    assert advanced.STATE["game"] is None


def test_partial_game_profile_failure_captures_and_restores_priority(monkeypatch):
    conn = memory_store(monkeypatch)
    class FakeProc:
        def __init__(self): self.priority = 3; self.affinity = [0, 1]
        def nice(self, value=None):
            if value is not None: self.priority = value
            return self.priority
        def cpu_affinity(self, value=None):
            if value is not None: self.affinity = list(value)
            return self.affinity
    proc = FakeProc()
    conn.execute("INSERT INTO actions VALUES(9,1,'game_profile_apply','failed','','{}')")
    conn.execute("INSERT INTO action_journal(action_id,kind,risk,created_at,before_json,undo_json,undo_available) VALUES(9,'game_profile_apply','medium',1,'{}',?,1)",
                 (json.dumps({"kind":"game_profile_apply","pid":321,"create_time":100,"exe":"c:/games/game.exe",
                              "priority_class":2,"cpu_affinity":[0,1],"default_cpu_sets":None,"background_processes":[]}),))
    conn.commit()
    monkeypatch.setattr(advanced, "_process_identity", lambda args: (proc, {"pid":321}))
    monkeypatch.setattr(advanced, "_get_process_default_cpu_sets", lambda pid: None)
    # Simulate the priority write succeeding before a later profile step failed.
    proc.priority = 3
    advanced.capture_failed_action_state(9)
    result = advanced.undo_action(9)
    assert result["ok"] is True
    assert proc.priority == 2


def test_updater_pause_requires_a_running_pre_action_service(monkeypatch):
    conn = memory_store(monkeypatch)
    monkeypatch.setattr(advanced, "IS_WIN", True)
    monkeypatch.setattr(advanced, "_service_state", lambda name: "stopped")
    conn.execute("INSERT INTO game_sessions(game_key,pid,create_time,started_at,before_json,status) VALUES('game.exe',123,1,1,'{}','active')")
    conn.commit()
    monkeypatch.setitem(advanced.STATE, "advanced", {"active_session_id": 1})
    try:
        advanced.prepare_action(99, "pause_updater_service", {"service": "gupdate"})
    except RuntimeError as exc:
        assert "not running" in str(exc)
    else:
        raise AssertionError("SENTINEL must not change an updater that was already stopped")


def test_wpr_capture_clears_shutdown_event_until_owned_trace_is_closed(monkeypatch, tmp_path):
    """WPR remains owned until its ETL is finalized and the completion event is released."""
    conn = memory_store(monkeypatch)
    conn.execute("CREATE TABLE trace_archive(ts REAL,file_path TEXT,size_bytes INTEGER,source TEXT,status TEXT)")
    conn.commit()
    monkeypatch.setattr(advanced, "IS_WIN", True)
    monkeypatch.setattr(advanced, "locate_wpr", lambda: r"C:\Windows\System32\wpr.exe")
    monkeypatch.setattr(advanced, "locate_xperf", lambda: None)
    monkeypatch.setattr(advanced.safeguard, "trace_preflight",
        lambda: {"allowed": True, "code": "ready", "reason": "test"})
    monkeypatch.setattr(advanced.safeguard, "snapshot",
        lambda **_kwargs: {"process_detection_complete": True, "valorant_active": False})
    monkeypatch.setattr(core, "TRACE_DIR", str(tmp_path))
    monkeypatch.setitem(advanced.STATE, "kernel", {"etw": {"recording": False}})
    advanced._ETW_OWNED = False
    advanced._ETW_DONE.set()

    class FastStop:
        def wait(self, _seconds):
            return False

    monkeypatch.setattr(advanced, "_STOP", FastStop())
    clock = [0.0]
    def monotonic():
        clock[0] += 2.0
        return clock[0]
    monkeypatch.setattr(advanced.time, "monotonic", monotonic)
    calls = []

    class Result:
        def __init__(self, args, stdout=""):
            self.args = args
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, timeout=15):
        calls.append(list(args))
        if args[1] == "-status":
            return Result(args, "There is no recording")
        if args[1] == "-start":
            return Result(args)
        if args[1] == "-stop":
            assert advanced._ETW_DONE.is_set() is False
            Path(args[-1]).write_bytes(b"synthetic ETL")
            return Result(args)
        raise AssertionError(f"unexpected WPR command: {args}")

    monkeypatch.setattr(advanced, "_run", fake_run)
    monkeypatch.setattr(advanced, "_decode_etl", lambda *_args: {
        "decoded": True, "event_count": 0, "named_driver_modules": []
    })

    result = advanced.capture_kernel_window(5)

    assert result["ok"] is True
    assert any(call[1] == "-start" for call in calls)
    assert any(call[1] == "-stop" for call in calls)
    assert result["xperf_optional"] is False
    assert advanced._ETW_OWNED is False
    assert advanced._ETW_DONE.is_set() is True
    assert conn.execute("SELECT COUNT(*) FROM trace_archive").fetchone()[0] == 1
