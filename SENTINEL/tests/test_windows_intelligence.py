import json

import pytest

from sentinel import windows_intelligence as specialist


def valid_payload():
    return {
        "diagnosis": "The adapter did not initialise successfully.",
        "confidence": "medium",
        "uncertainty": "A device error code is required to narrow the cause.",
        "evidence_used": ["metric.cpu_pct", "sentinel-kb:doc:0"],
        "extra_probes": ["Read the adapter problem code from Device Manager."],
        "recommendations": [{
            "title": "Inspect the exact adapter state",
            "rationale": "Confirm the current device problem code before repair.",
            "action_id": None,
        }],
        "safety_notes": ["No network reset has been performed."],
    }


def test_specialist_accepts_only_supplied_evidence_and_known_actions():
    result = specialist._validate_response(
        json.dumps(valid_payload()),
        valid_refs={"sentinel-kb:doc:0"},
        valid_evidence={"metric.cpu_pct"},
    )
    assert result["confidence"] == "medium"
    assert result["recommendations"][0]["executed"] is False


def test_specialist_rejects_fabricated_citation():
    payload = valid_payload()
    payload["evidence_used"] = ["sentinel-kb:made-up:0"]
    with pytest.raises(RuntimeError, match="cited evidence"):
        specialist._validate_response(json.dumps(payload), valid_refs={"sentinel-kb:doc:0"}, valid_evidence={"metric.cpu_pct"})


def test_specialist_rejects_unknown_action_id():
    payload = valid_payload()
    payload["recommendations"][0]["action_id"] = "run_powershell"
    with pytest.raises(RuntimeError, match="fixed maintenance vocabulary"):
        specialist._validate_response(json.dumps(payload), valid_refs={"sentinel-kb:doc:0"}, valid_evidence={"metric.cpu_pct"})


def test_specialist_rejects_extra_command_fields():
    payload = valid_payload()
    payload["command"] = "format C:"
    with pytest.raises(RuntimeError, match="schema"):
        specialist._validate_response(json.dumps(payload), valid_refs={"sentinel-kb:doc:0"}, valid_evidence={"metric.cpu_pct"})


def test_specialist_question_is_bounded_and_requires_local_model(monkeypatch):
    with pytest.raises(ValueError):
        specialist.diagnose(" ")
    with pytest.raises(ValueError):
        specialist.diagnose("x" * 501)


def test_specialist_rejects_non_string_action_identifier():
    payload = valid_payload()
    payload["recommendations"][0]["action_id"] = ["cleanup"]
    with pytest.raises(RuntimeError, match="fixed maintenance vocabulary"):
        specialist._validate_response(json.dumps(payload), valid_refs={"sentinel-kb:doc:0"}, valid_evidence={"metric.cpu_pct"})



def test_evidence_packet_fuses_windows_sources_without_private_process_content(monkeypatch):
    from sentinel import core, inventory

    monkeypatch.setattr(core, "LIVE", {
        "cpu": 42.5, "mem": 67.0, "dpc": 1.2, "loss": 0.0,
    })
    monkeypatch.setattr(core, "STATE", {
        "system": {"os": "Windows 11", "windows_build": "26300", "cpu_name": "Core i5"},
        "game": False,
        "proc_total": 25,
        "proc_inaccessible": 1,
        "proc_recommendations": [{"pid": 202, "name": "editor.exe"}],
        "procs": [{
            "pid": 101, "name": "helper.exe", "exe": r"C:\Users\private-user\helper.exe",
            "cmdline": "--password=super-secret", "window_title": "Private document title",
            "cpu_percent": 12.5, "rss_mb": 250, "session_id": 1,
            "visible_windows": 1, "onscreen_windows": 1,
        }],
        "services": {"running": 80, "total": 125, "vanguard": {"vgc": "running", "vgk": "running"}},
        "services_catalog": [{
            "name": "VendorHelper", "display": "Vendor Helper", "state": "stopped",
            "start": "manual", "pid": 0, "description": "Optional helper",
            "binpath": r"C:\Users\private-user\vendor.exe", "username": "DOMAIN\user",
        }],
        "startup": [{"name": "VendorTray", "where": "HKCU\Run",
                     "cmd": r"C:\Users\private-user\vendor.exe --token=private"}],
        "maintenance": {
            "drivers": [{"DeviceName": "Realtek Network Adapter", "DriverVersion": "1.2.3",
                         "DriverDate": "2026-01-01", "Manufacturer": "Realtek", "DeviceClass": "NET"}],
            "driver_updates": [{"title": "Realtek - Net - update available", "reboot_required": False,
                                "hardware_ids": ["PRIVATE-HARDWARE-ID"]}],
            "system_health": {"findings": [{"code": "memory_pressure", "severity": "medium",
                                             "title": "Memory pressure", "detail": "Working set increased"}]},
        },
    })
    monkeypatch.setattr(inventory, "INV", {
        "ts": 1000.0,
        "health": {"apps": {"ok": True}, "drivers": {"ok": False, "error": "provider unavailable"}},
        "apps": [{"name": "Brave Browser", "version": "1.0", "publisher": "Brave"}],
        "tasks": [{"name": "VendorUpdater", "state": "Ready", "path": r"\Vendor\Updater"}],
    })

    def fake_db(sql, args=(), many=False):
        if "SELECT id,ts,level,src,msg FROM events" in sql:
            return [(77, 990.0, "error", "eventlog", "Application Error event")]
        if "SELECT id,sev,key,title,detail FROM insights" in sql:
            return [(12, "warn", "memory", "Memory pressure", "Available memory decreased")]
        if "FROM activity_apps" in sql:
            return [("Brave Browser", 5, 7200.0, 995.0)]
        if "FROM agent_assist_feedback" in sql:
            return [("process-review", "Background application review", "Keep my audio and touchpad utilities enabled")]
        return []

    monkeypatch.setattr(core, "db", fake_db)
    packet = specialist._evidence_packet()
    serialized = json.dumps(packet, ensure_ascii=False)

    assert packet["process_summary"]["observed"] == 25
    assert packet["top_processes_by_resource"][0]["id"] == "process.101"
    assert packet["services"]["rows"][0]["state"] == "stopped"
    assert packet["driver_updates"][0]["id"].startswith("driver-update.")
    assert packet["recent_events_7d"][0]["id"] == "event.77"
    assert packet["application_usage_30d"][0]["foreground_hours_30d"] == 2.0
    assert packet["prior_user_answers"][0]["preference"].startswith("Keep my audio")
    assert "service.VendorHelper" in packet["evidence_ids"]
    assert "event.77" in packet["evidence_ids"]
    assert "Private document title" not in serialized
    assert "super-secret" not in serialized
    assert "vendor.exe --token" not in serialized
    assert "DOMAIN" not in serialized


def test_specialist_accepts_cross_subsystem_evidence_ids():
    payload = valid_payload()
    payload["evidence_used"] = ["process.101", "service.VendorHelper", "event.77"]
    result = specialist._validate_response(
        json.dumps(payload),
        valid_refs=set(),
        valid_evidence={"process.101", "service.VendorHelper", "event.77"},
    )
    assert result["evidence_used"] == payload["evidence_used"]
