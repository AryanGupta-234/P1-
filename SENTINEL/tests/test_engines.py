import time

from sentinel import core, safeguard, runtime_engine, memory_engine, security_engine


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
