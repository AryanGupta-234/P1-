import json
import sqlite3
from types import SimpleNamespace

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
        [{"pid": 4242, "create_time": 1792557200.0, "name": "reused-pid.exe"}],
    )

    parsed = advanced._parse_etw_xml(str(xml), trace_end=1792555205.0)

    assert parsed["ok"] is True
    assert parsed["events"][0]["pid"] == 4242
    assert parsed["events"][0]["process_name"] is None
    assert parsed["process_attribution_count"] == 0
    assert parsed["unattributed_event_count"] == 1


def test_etw_parser_does_not_apply_a_future_pid_reuse_start_to_earlier_events(tmp_path, monkeypatch):
    xml = tmp_path / "pid-reuse-in-trace.xml"
    xml.write_text(
        "<Events>"
        + _event(
            "NT Kernel Logger", 66, "DPC", "Execute", 4242, {},
            "2026-10-21T04:00:00.500Z",
        )
        + _event(
            "Microsoft-Windows-Kernel-Process", 1, "Process", "Start", 4,
            {"ProcessID": "4242", "ImageFileName": r"C:\Games\new-game.exe"},
            "2026-10-21T04:00:01.000Z",
        )
        + _event(
            "NT Kernel Logger", 66, "DPC", "Execute", 4242, {},
            "2026-10-21T04:00:01.500Z",
        )
        + "</Events>",
        encoding="utf-8",
    )
    # Keep the fallback empty so this test covers only in-trace ProcessStart evidence.
    monkeypatch.setitem(advanced.STATE, "procs", [])
    parsed = advanced._parse_etw_xml(str(xml), trace_end=1792555205.0)

    dpc = [item for item in parsed["events"] if item["event_name"].startswith("DPC")]
    assert len(dpc) == 2
    assert dpc[0]["process_name"] is None
    assert dpc[1]["process_name"] == "new-game.exe"


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
    monkeypatch.setattr(advanced, "_lhm_library_sensors", lambda: ([], "direct reader not used in this WMI test"))
    monkeypatch.setattr(advanced, "_lhm_rest_sensors", lambda _port: ([], "loopback REST server not enabled"))

    result = advanced._lhm_sample()

    assert result["available"] is True, result
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
    # A delayed restore retry must not replace the end-of-game evidence snapshot.
    monkeypatch.setattr(advanced, "_current_metrics", lambda: {"cpu": 99.0})
    second = advanced._end_game_session(1, 230.0)
    status2 = conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0]
    saved = conn.execute("SELECT ended_at,after_json,report_json FROM game_sessions WHERE id=1").fetchone()

    assert first["restoration_pending"] is True
    assert status1 == "restore_pending"
    assert second["restoration_pending"] is False
    assert status2 == "completed"
    assert saved[0] == 200.0
    assert json.loads(saved[1]) == {"cpu": 20.0}
    assert json.loads(saved[2])["duration_seconds"] == 100.0
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

def test_game_session_teardown_retries_real_power_plan_undo(monkeypatch):
    conn = _memory_store(monkeypatch)
    conn.execute(
        """INSERT INTO actions VALUES(77,100,'power_plan','done','changed','{}')"""
    )
    conn.execute(
        """INSERT INTO action_journal(
            action_id,kind,risk,created_at,before_json,undo_json,undo_available,changed
        ) VALUES(77,'power_plan','medium',100,'{}',?,1,1)""",
        (json.dumps({
            "kind": "power_plan",
            "power_plan": "381b4222-f694-41f0-9685-ff5bb260df2e",
            "applied_plan": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        }),),
    )
    conn.execute(
        """INSERT INTO game_sessions(
            game_key,pid,create_time,started_at,before_json,status
        ) VALUES('game.exe',4242,100,100,'{}','active')"""
    )
    conn.execute(
        "INSERT INTO session_actions(session_id,action_id,created_at) VALUES(1,77,101)"
    )
    conn.commit()
    monkeypatch.setitem(advanced.CFG, "advanced", {"auto_report_sessions": True})
    monkeypatch.setattr(advanced, "_current_metrics", lambda: {"cpu": 20.0})
    monkeypatch.setattr(advanced, "_correlate_window", lambda *_args: [])
    monkeypatch.setattr(advanced, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(advanced, "publish", lambda *_args, **_kwargs: None)

    system = {"power_plan": None}
    monkeypatch.setattr(advanced, "_power_plan", lambda: system["power_plan"])

    def fake_run(args, timeout=15):
        assert args[:2] == ["powercfg.exe", "/setactive"]
        system["power_plan"] = args[2]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(advanced, "_run", fake_run)

    first = advanced._end_game_session(1, 200.0)
    journal1 = conn.execute(
        "SELECT reverted_at,revert_result FROM action_journal WHERE action_id=77"
    ).fetchone()
    assert first["restoration_pending"] is True
    assert conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0] == "restore_pending"
    assert journal1[0] is None
    assert "active power scheme is unknown" in journal1[1]

    # The same exact action remains retryable once Windows exposes its current state.
    system["power_plan"] = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    second = advanced._end_game_session(1, 230.0)
    journal2 = conn.execute(
        "SELECT reverted_at,revert_result FROM action_journal WHERE action_id=77"
    ).fetchone()
    assert second["restoration_pending"] is False
    assert system["power_plan"] == "381b4222-f694-41f0-9685-ff5bb260df2e"
    assert journal2[0] is not None
    assert conn.execute("SELECT status FROM game_sessions WHERE id=1").fetchone()[0] == "completed"
    assert conn.execute("SELECT ended_at FROM game_sessions WHERE id=1").fetchone()[0] == 200.0

def test_game_profile_undo_remains_pending_when_post_apply_snapshot_is_missing(monkeypatch):
    conn = _memory_store(monkeypatch)
    conn.execute(
        """INSERT INTO action_journal(
            action_id,kind,risk,created_at,before_json,undo_json,undo_available,changed
        ) VALUES(88,'game_profile_apply','medium',100,'{}',?,1,1)""",
        (json.dumps({
            "kind": "game_profile_apply",
            "pid": 4242,
            "create_time": 100.0,
            "exe": "C:/Games/game.exe",
            "priority_class": 2,
            "cpu_affinity": [0, 1],
            "default_cpu_sets": [0, 1],
            "applied_process_state_captured": False,
            "applied_default_cpu_sets": None,
            "background_processes": [],
            "timer_applied_ms": 0,
            "power_plan": None,
        }),),
    )
    conn.commit()

    class FakeProc:
        def nice(self, value=None):
            return 3
        def cpu_affinity(self, value=None):
            return [0, 1]

    monkeypatch.setattr(advanced, "_process_identity", lambda _args: (FakeProc(), {}))
    monkeypatch.setattr(advanced, "_get_process_default_cpu_sets", lambda _pid: None)
    monkeypatch.setattr(advanced, "log", lambda *_args, **_kwargs: None)

    result = advanced.undo_action(88)
    row = conn.execute(
        "SELECT reverted_at,revert_result FROM action_journal WHERE action_id=88"
    ).fetchone()

    assert result["ok"] is False
    assert "post-apply process snapshot unavailable" in result["error"]
    assert row[0] is None
    assert "retry required" in row[1]

def test_lhm_rest_fallback_reads_loopback_data_json_and_maps_asus_fans(monkeypatch):
    monkeypatch.setattr(advanced, "IS_WIN", True)
    monkeypatch.setitem(advanced.CFG, "advanced", {"lhm_enabled": True, "lhm_http_port": 8085})
    monkeypatch.setattr(advanced, "_lhm_wmi_sensors", lambda: ([], "WMI namespace unavailable"))
    monkeypatch.setattr(advanced, "_lhm_library_sensors", lambda: ([], "direct reader not used in this REST test"))

    tree = {
        "Version": "0.9.6",
        "Text": "Sensor",
        "Children": [
            {
                "Text": "Intel Core i5-12500H",
                "HardwareId": "/intelcpu/0",
                "Children": [
                    {
                        "Text": "Temperatures",
                        "Children": [
                            {
                                "Text": "CPU Package",
                                "SensorId": "/intelcpu/0/temperature/0",
                                "Type": "Temperature",
                                "RawValue": "76.5 °C",
                                "Children": [],
                            },
                            {
                                "Text": "Core #0",
                                "SensorId": "/intelcpu/0/temperature/1",
                                "Type": "Temperature",
                                "RawValue": "74.0 °C",
                                "Children": [],
                            },
                        ],
                    }
                ],
            },
            {
                "Text": "ASUS Embedded Controller",
                "HardwareId": "/lpc/asus_ec",
                "Children": [
                    {
                        "Text": "Fans",
                        "Children": [
                            {
                                "Text": "CPU Fan",
                                "SensorId": "/lpc/asus_ec/fan/0",
                                "Type": "Fan",
                                "RawValue": "2300 RPM",
                                "Children": [],
                            }
                        ],
                    }
                ],
            },
            {
                "Text": "NVIDIA GeForce RTX",
                "HardwareId": "/nvidiagpu/0",
                "Children": [
                    {
                        "Text": "GPU Core",
                        "SensorId": "/nvidiagpu/0/temperature/0",
                        "Type": "Temperature",
                        "RawValue": "65.0 °C",
                        "Children": [],
                    }
                ],
            },
        ],
    }

    class FakeResponse:
        status = 200
        reason = "OK"

        def read(self, _limit=-1):
            return json.dumps(tree).encode("utf-8")

    class FakeConnection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1"
            assert port == 8085
            assert timeout == 3
            self.request_args = None
            self.closed = False

        def request(self, method, path, headers=None):
            self.request_args = (method, path, headers or {})
            assert method == "GET"
            assert path == "/data.json"
            assert self.request_args[2].get("Accept") == "application/json"

        def getresponse(self):
            return FakeResponse()

        def close(self):
            self.closed = True

    connections = []

    def connection_factory(*args, **kwargs):
        connection = FakeConnection(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(advanced, "HTTPConnection", connection_factory)

    result = advanced._lhm_sample()

    assert result["available"] is True, result
    assert result["provider"] == "LibreHardwareMonitor 0.9.6"
    assert result["source"] == "loopback REST /data.json"
    assert result["rest_used"] is True
    assert result["cpu_sensor_count"] == 2
    assert result["per_core_temperatures"][0]["name"] == "Core #0"
    assert result["fan_sensor_count"] == 1
    assert result["fan_rpm"][0]["value"] == 2300.0
    assert result["fan_rpm"][0]["parent"].startswith("ASUS Embedded Controller")
    assert all("GPU" not in item["name"] for item in result["cpu_temperatures"])
    assert connections[0].closed is True


def test_lhm_rest_reader_refuses_non_success_and_never_follows_redirects(monkeypatch):
    class UnauthorizedResponse:
        status = 401
        reason = "Unauthorized"

        def read(self, _limit=-1):
            return b"auth required"

    class FakeConnection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1"
            self.calls = []

        def request(self, method, path, headers=None):
            self.calls.append((method, path))

        def getresponse(self):
            return UnauthorizedResponse()

        def close(self):
            pass

    monkeypatch.setattr(advanced, "HTTPConnection", FakeConnection)
    rows, reason = advanced._lhm_rest_sensors(8085)
    assert rows == []
    assert "HTTP 401" in reason

def test_xperf_dpcisr_parser_only_emits_explicit_driver_modules(tmp_path):
    report = tmp_path / "dpcisr.txt"
    report.write_text(
        "Module: nvlddmkm.sys Routine: 0xFFFFF 123.4 5.6\n"
        "Module: tcpip.sys Routine: 0xFFFFA 42.0 2.0\n"
        "No module name resolved for this DPC\n",
        encoding="utf-8",
    )

    drivers = advanced._parse_dpc_report(str(report))

    assert [item["module"] for item in drivers] == ["nvlddmkm.sys", "tcpip.sys"]
    assert all("xperf dpcisr summary" in item["attribution"] for item in drivers)

