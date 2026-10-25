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
