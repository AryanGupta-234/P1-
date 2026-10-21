import time

from sentinel import core, safeguard, runtime_engine, memory_engine, security_engine, ai_engine


def test_safeguard_blocks_mutations_during_valorant(monkeypatch):
    now = time.time()
    monkeypatch.setitem(core.STATE, "procs", [{
        "pid": 4120, "create_time": now - 20, "name": "VALORANT-Win64-Shipping.exe",
        "exe": r"C:\Riot Games\VALORANT\live\ShooterGame\Binaries\Win64\VALORANT-Win64-Shipping.exe",
    }])
    monkeypatch.setitem(core.STATE, "proc_scan_at", now)
    decision = safeguard.check_action("power_plan")
    assert decision["allowed"] is False
    assert decision["code"] == "valorant_read_only"
    assert safeguard.check_action("etw_capture")["allowed"] is False


def test_safeguard_protects_riot_and_windows_process_identities():
    assert safeguard.is_protected_process("vgc.exe")
    assert safeguard.is_protected_process("VALORANT-Win64-Shipping.exe")
    assert safeguard.is_protected_process("lsass.exe")
    assert not safeguard.is_protected_process("notepad.exe")


def test_valorant_game_profile_is_always_forbidden(monkeypatch):
    monkeypatch.setitem(core.STATE, "game", None)
    decision = safeguard.check_action("game_profile_apply", {
        "game": "VALORANT-Win64-Shipping.exe",
        "exe": r"C:\Riot Games\VALORANT\VALORANT-Win64-Shipping.exe",
    })
    assert not decision["allowed"]
    assert decision["code"] == "valorant_profile_forbidden"


def test_memory_engine_context_budget_is_bounded():
    payload = {"top_processes": [{"name": "x" * 200} for _ in range(40)], "recent_etw_events": list(range(40))}
    compacted = memory_engine.compact(payload, "triage")
    assert len(str(compacted)) <= memory_engine.budgets()["triage_chars"] + 200
    assert len(compacted["top_processes"]) <= memory_engine.budgets()["process_rows"]


def test_process_assessment_is_advisory_and_does_not_guess_signature():
    result = security_engine.assess_process({
        "name": "payload.exe",
        "exe": r"C:\Users\Public\payload.exe",
        "path_state": "present",
        "parent_name": "powershell.exe",
        "session_id": 1,
    })
    assert result["level"] in ("review", "high")
    assert "not queried" in result["signature"]
    assert "malware" in result["assessment_limit"]


def test_adaptive_runtime_does_not_allow_deep_ai_during_valorant(monkeypatch):
    now = time.time()
    monkeypatch.setitem(core.STATE, "procs", [{
        "pid": 4120, "create_time": now - 20, "name": "VALORANT-Win64-Shipping.exe",
        "exe": r"C:\Riot Games\VALORANT\VALORANT-Win64-Shipping.exe",
    }])
    monkeypatch.setitem(core.STATE, "proc_scan_at", now)
    monkeypatch.setitem(core.STATE, "game", {"name": "VALORANT-Win64-Shipping.exe", "pid": 4120})
    state = runtime_engine.evaluate()
    assert state["mode"] == "valorant_guarded"
    assert not state["deep_ai_allowed"]
    assert not state["wpr_allowed"]


def test_disabled_process_monitor_fails_closed(monkeypatch):
    monkeypatch.setattr(core, "off", lambda _name: True)
    decision = safeguard.check_action("power_plan")
    assert not decision["allowed"]
    assert decision["code"] == "process_state_unknown"


def test_unknown_process_state_blocks_mutations_and_inference(monkeypatch):
    monkeypatch.setattr(core, "off", lambda _name: True)
    guard = safeguard.snapshot()
    assert guard["process_detection_complete"] is False
    assert safeguard.check_action("power_plan")["allowed"] is False
    allowed, _reason = ai_engine.inference_allowed("local-test-model", cloud=False)
    assert allowed is False


def test_runtime_marks_disabled_process_observer_as_degraded(monkeypatch):
    monkeypatch.setattr(core, "off", lambda _name: True)
    state = runtime_engine.evaluate()
    assert state["mode"] == "safety_degraded"
    assert state["deep_ai_allowed"] is False
    assert state["fast_ai_allowed"] is False



def test_new_process_observation_retains_safe_review_identity():
    item = security_engine.observe_process_start({
        "pid": 5100,
        "create_time": 123.5,
        "name": "sample.exe",
        "exe": r"C:\Users\Public\sample.exe",
        "parent_name": "explorer.exe",
        "parent_pid": 800,
        "session_id": 1,
        "visible_windows": 1,
        "onscreen_windows": 1,
        "path_state": "present",
    })
    assert item["pid"] == 5100
    assert item["create_time"] == 123.5
    assert item["visible_windows"] == 1
    assert item["onscreen_windows"] == 1
    assert item["path_state"] == "present"


def test_cloud_and_local_ai_are_both_paused_during_a_game(monkeypatch):
    now = time.time()
    monkeypatch.setitem(core.STATE, "procs", [{
        "pid": 5200, "create_time": now - 10, "name": "game.exe",
        "exe": r"C:\Games\game.exe",
    }])
    monkeypatch.setitem(core.STATE, "proc_scan_at", now)
    monkeypatch.setitem(core.STATE, "game", {"name": "game.exe", "pid": 5200})
    local_allowed, _ = ai_engine.inference_allowed("local-model", cloud=False, pause_when_gaming=True, slot="fast")
    cloud_allowed, _ = ai_engine.inference_allowed("☁ cloud-model", cloud=True, pause_when_gaming=True, slot="fast")
    assert not local_allowed
    assert not cloud_allowed


def test_valorant_inspection_is_rejected_before_file_access(monkeypatch):
    monkeypatch.setattr(core, "IS_WIN", True)
    now = time.time()
    monkeypatch.setitem(core.STATE, "procs", [{
        "pid": 4120, "create_time": now - 20, "name": "VALORANT-Win64-Shipping.exe",
        "exe": r"C:\Riot Games\VALORANT\VALORANT-Win64-Shipping.exe",
    }])
    monkeypatch.setitem(core.STATE, "proc_scan_at", now)
    try:
        security_engine.inspect_process(4120, now - 20,
            r"C:\Riot Games\VALORANT\VALORANT-Win64-Shipping.exe", "sha256")
    except PermissionError as exc:
        assert "VALORANT is active" in str(exc)
    else:
        raise AssertionError("VALORANT inspection should be rejected")


def test_process_inspection_rejects_unknown_operations(monkeypatch):
    monkeypatch.setattr(core, "IS_WIN", True)
    try:
        security_engine.inspect_process(100, 123.0, r"C:\test.exe", "dump-memory")
    except ValueError as exc:
        assert "operation must be" in str(exc)
    else:
        raise AssertionError("unlisted process-inspection operations must be rejected")
