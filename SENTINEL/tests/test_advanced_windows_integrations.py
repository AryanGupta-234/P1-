import json
import sqlite3

from sentinel import advanced


def _memory_store(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    def execute(sql, args=()):
        cursor = conn.execute(sql, args)
        rows = cursor.fetchall() if sql.lstrip().lower().startswith("select") else []
        conn.commit()
        return rows

    monkeypatch.setattr(advanced, "db", execute)
    advanced._ensure_schema()
    conn.execute(
        "CREATE TABLE events(id INTEGER PRIMARY KEY,ts REAL,level TEXT,src TEXT,msg TEXT,data TEXT)"
    )
    conn.execute(
        "CREATE TABLE actions(id INTEGER PRIMARY KEY,ts REAL,kind TEXT,state TEXT,result TEXT,args TEXT)"
    )
    conn.commit()
    return conn


def _event(provider, event_id, task, opcode, execution_pid, fields, timestamp):
    data = "".join(
        f'<Data Name="{name}">{value}</Data>' for name, value in fields.items()
    )
    return (
        "<Event><System>"
        f'<Provider Name="{provider}"/><EventID>{event_id}</EventID>'
        f"<Task>{task}</Task><Opcode>{opcode}</Opcode>"
        f'<TimeCreated SystemTime="{timestamp}"/>'
        f'<Execution ProcessID="{execution_pid}" ThreadID="77"/>'
        f"</System><EventData>{data}</EventData></Event>"
    )


def test_etw_parser_uses_process_start_events_and_explicit_driver_modules(tmp_path):
    xml = tmp_path / "kernel.xml"
    xml.write_text(
        "<Events>"
        + _event(
            "Microsoft-Windows-Kernel-Process",
            1,
            "Process",
            "Start",
            4,
            {"ProcessID": "4242", "ImageFileName": r"C:\Games\game.exe"},
            "2026-10-21T04:00:00.100Z",
        )
        + _event(
            "NT Kernel Logger",
            66,
            "DPC",
            "Execute",
            4242,
            {"ModuleName": r"C:\Windows\System32\drivers\nvlddmkm.sys", "DpcTimeUs": "123.4"},
            "2026-10-21T04:00:01.250Z",
        )
        + "</Events>",
        encoding="utf-8",
    )

    parsed = advanced._parse_etw_xml(str(xml), trace_end=1792555205.0)

    assert parsed["ok"] is True
    assert parsed["process_start_count"] == 1
    assert parsed["process_attribution_count"] == 2
    dpc = next(item for item in parsed["events"] if item["event_name"].startswith("DPC"))
    assert dpc["pid"] == 4242
    assert dpc["process_name"] == "game.exe"
    assert dpc["module_name"] == "nvlddmkm.sys"
    assert dpc["duration_us"] == 123.4
    assert dpc["ts"] < 1792555205.0


def test_etw_parser_rejects_live_pid_name_when_process_started_after_trace(tmp_path, monkeypatch):
    xml = tmp_path / "stale-pid.xml"
    xml.write_text(
        "<Events>"
        + _event(
            "NT Kernel Logger",
            66,
            "DPC",
            "Execute",
            4242,
            {},
            "2026-10-21T04:00:01.250Z",
        )
        + "</Events>",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        advanced.STATE,
        "procs",
        [{"pid": 4242, "create_time": 2000.0, "name": "reused-pid.exe"}],
    )

    parsed = advanced._parse_etw_xml(str(xml), trace_end=1000.0)

    assert parsed["ok"] is True
    assert parsed["events"][0]["pid"] == 4242
    assert parsed["events"][0]["process_name"] is None
    assert parsed["process_attribution_count"] == 0
    assert parsed["unattributed_event_count"] == 1


def test_lhm_reader_supports_asus_cpu_core_and_fan_sensor_names(monkeypatch):
    monkeypatch.setattr(advanced, "IS_WIN", True)
    monkeypatch.setitem(advanced.CFG, "advanced", {"lhm_enabled": True})
    payload = {
        "namespace": r"root\LibreHardwareMonitor",
        "sensors": [
            {
                "Name": "CPU Package",
                "Parent": "Intel Core i5-12500H",
                "SensorType": "Temperature",
                "Value": 76.5,
                "Identifier": "/intelcpu/0/temperature/0",
            },
            {
                "Name": "CPU Core #0",
                "Parent": "Intel Core i5-12500H",
                "SensorType": "Temperature",
                "Value": 74.0,
                "Identifier": "/intelcpu/0/temperature/1",
            },
            {
                "Name": "CPU Fan",
                "Parent": "ASUS Embedded Controller",
                "SensorType": "Fan",
                "Value": 2300,
                "Identifier": "/lpc/nct6798d/fan/0",
            },
            {
                "Name": "GPU Core",
                "Parent": "NVIDIA GeForce RTX",
                "SensorType": "Temperature",
                "Value": 65.0,
                "Identifier": "/nvidiagpu/0/temperature/0",
            },
        ],
    }
    calls = []

    def fake_run(args, timeout=15):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(advanced, "_run", fake_run)

    result = advanced._lhm_sample()

    assert result["available"] is True
    assert result["provider"] == "LibreHardwareMonitor"
    assert result["cpu_sensor_count"] == 2
    assert result["fan_sensor_count"] == 1
    assert result["cpu_temperatures"][0]["value"] == 76.5
    assert result["per_core_temperatures"][0]["name"] == "CPU Core #0"
    assert result["fan_rpm"][0]["value"] == 2300
    powershell_script = calls[0][-1]
    assert r"root\LibreHardwareMonitor" in powershell_script
    assert r"root\OpenHardwareMonitor" in powershell_script
    assert r"root\\LibreHardwareMonitor" not in powershell_script


def test_failed_game_session_undo_remains_pending_until_retry_succeeds(monkeypatch):
    conn = _memory_store(monkeypatch)
    conn.execute(
        "INSERT INTO actions VALUES(55,100,'game_profile_apply','done','','{}')"
    )
    conn.execute(
        """INSERT INTO action_journal(
            action_id,kind,risk,created_at,before_json,undo_json,undo_available,changed
        ) VALUES(55,'game_profile_apply','medium',100,'{}','{}',1,1)"""
    )
    conn.execute(
        """INSERT INTO game_sessions(
            game_key,pid,create_time,started_at,before_json,profile_action_id,status
        ) VALUES('game.exe',4242,100,100,'{}',55,'active')"""
    )
    conn.execute(
        "INSERT INTO session_actions(session_id,action_id,created_at) VALUES(1,55,101)"
    )
    conn.commit()
    monkeypatch.setitem(advanced.CFG, "advanced", {"auto_report_sessions": True})
    monkeypatch.setattr(advanced, "_current_metrics", lambda: {"cpu": 20.0})
    monkeypatch.setattr(advanced, "_correlate_window", lambda *_args: [])
    monkeypatch.setattr(advanced, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(advanced, "publish", lambda *_args, **_kwargs: None)

    attempts = []

    def undo(action_id):
        attempts.append(action_id)
        if len(attempts) == 1:
            return {"ok": False, "error": "simulated Windows restore failure"}
        conn.execute(
            "UPDATE action_journal SET reverted_at=230,revert_result='restored' WHERE action_id=?",
            (action_id,),
        )
        conn.commit()
        return {"ok": True, "result": "restored on retry"}

    monkeypatch.setattr(advanced, "undo_action", undo)

    first = advanced._end_game_session(1, 200.0)
    status1 = conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0]
    second = advanced._end_game_session(1, 230.0)
    status2 = conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0]

    assert first["restoration_pending"] is True
    assert status1 == "restore_pending"
    assert second["restoration_pending"] is False
    assert status2 == "completed"
    # profile_action_id and session_actions may both reference the same action;
    # teardown must still attempt it exactly once per pass.
    assert attempts == [55, 55]


def test_startup_retries_restore_pending_session_instead_of_resuming_game(monkeypatch):
    conn = _memory_store(monkeypatch)
    conn.execute(
        """INSERT INTO game_sessions(
            game_key,pid,create_time,started_at,before_json,status,ended_at
        ) VALUES('game.exe',4242,100,100,'{}','restore_pending',200)"""
    )
    conn.commit()
    calls = []
    monkeypatch.setattr(
        advanced,
        "_end_game_session",
        lambda session_id, ts: calls.append((session_id, ts)) or {"duration_seconds": 100},
    )
    monkeypatch.setitem(advanced.STATE, "advanced", {})
    monkeypatch.setitem(advanced.STATE, "game", None)
    monkeypatch.setattr(advanced, "log", lambda *_args, **_kwargs: None)

    advanced._recover_interrupted_sessions()

    assert len(calls) == 1
    assert calls[0][0] == 1
    assert "active_session_id" not in advanced.STATE["advanced"]
