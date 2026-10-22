import time

from sentinel import core, safeguard, runtime_engine, memory_engine, security_engine, ai_engine, advanced
from types import SimpleNamespace


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


def test_wpr_status_parser_recognizes_documented_active_and_inactive_messages():
    active = SimpleNamespace(returncode=0, stdout="WPR recording is in progress...\\nTime since start: 00:00:05", stderr="")
    inactive = SimpleNamespace(returncode=0, stdout="There are no trace profiles running.", stderr="")
    assert advanced._wpr_recording_state(active) is True
    assert advanced._wpr_recording_state(inactive) is False


def test_cloud_ai_is_paused_during_games_when_game_pause_policy_is_enabled(monkeypatch):
    now = time.time()
    monkeypatch.setitem(core.STATE, "procs", [])
    monkeypatch.setitem(core.STATE, "proc_scan_at", now)
    monkeypatch.setitem(core.STATE, "game", {"name": "another-game.exe", "pid": 9001})
    allowed, reason = ai_engine.inference_allowed(
        "cloud-test", cloud=True, pause_when_gaming=True, slot="fast"
    )
    assert not allowed
    assert "all model inference paused" in reason


def test_script_host_plus_nonstandard_user_image_creates_review_signal():
    result = security_engine.assess_process({
        "name": "utility.exe",
        "exe": r"C:\\Users\\Example\\Documents\\utility.exe",
        "path_state": "present",
        "parent_name": "powershell.exe",
        "session_id": 1,
    })
    assert result["level"] == "review"
    assert result["score"] >= 35
