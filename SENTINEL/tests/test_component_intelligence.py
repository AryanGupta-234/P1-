import os
import time

import pytest

from sentinel import component_intelligence as components
from sentinel import core, actions


def _process_summary(component_id=None, *, samples=900, days=12, span_hours=288,
                    signature="Valid", publisher="Example Software Ltd.",
                    signer="CN=Example Software Ltd.", protected=0, cpu=0.75,
                    memory=360.0, io_rate=0.65, foreground=0.002, visible=0.0,
                    visible_ratio=0.0, onscreen_ratio=0.0, dependents="[]"):
    now = time.time()
    return (
        component_id or ("process:" + "a" * 40),
        "process", "Example Helper", "ExampleHelper.exe", publisher,
        "Example Helper", "2.4.1", signature, signer,
        protected, "[]", dependents, "", "running",
        now - span_hours * 3600, now, samples, days,
        now - span_hours * 3600, now,
        cpu, 8.5, memory, 520.0, io_rate, foreground, visible, visible, 1.0, now,
        visible_ratio, onscreen_ratio,
    )


def _service_summary(component_id=None, *, samples=520, days=9, span_hours=216,
                     signature="Valid", publisher="Example Software Ltd.",
                     signer="CN=Example Software Ltd.", protected=0,
                     start_mode="auto", state="running", dependents="[]"):
    now = time.time()
    return (
        component_id or ("service:" + "b" * 40),
        "service", "ExampleVendorService", "ExampleService.exe", publisher,
        "Example Product", "3.2.0", signature, signer,
        protected, '["RpcSs"]', dependents, start_mode, state,
        now - span_hours * 3600, now, samples, days,
        now - span_hours * 3600, now,
        None, None, None, None, None, None, None, None, 1.0, now,
        0.0, 0.0,
    )


def test_component_identity_is_repeatable_and_does_not_store_executable_path():
    path = r"C:\Program Files\Example\ExampleHelper.exe"
    component_id = components.process_component_id(path)
    assert component_id
    assert component_id == components.process_component_id(path)
    assert component_id.startswith("process:")
    assert path.casefold() not in component_id.casefold()
    assert len(component_id.split(":", 1)[1]) == 40


def test_component_notes_redact_user_paths_accounts_and_secrets():
    note = components._clean(
        r"Touchpad helper under C:\Users\private-user\AppData\Local; DOMAIN\private-user token=secret-value"
    )
    assert "private-user" not in note
    assert "secret-value" not in note
    assert "[USER]" in note
    assert "[ACCOUNT]" in note


def test_service_identity_is_stable_and_name_scoped():
    assert components.service_component_id("ExampleSvc") == components.service_component_id("examplesvc")
    assert components.service_component_id("ExampleSvc").startswith("service:")
    assert components.service_component_id("") is None


def test_process_review_candidate_requires_signed_history_and_measured_background_resource_use():
    candidate = components._process_candidate(_process_summary(), {}, [])
    assert candidate is not None
    assert candidate["evidence_strength"] == "high"
    assert candidate["sample_count"] == 900
    assert candidate["active_days"] == 12
    assert candidate["average_memory_mb"] == 360.0
    assert candidate["signature_status"] == "Valid"
    assert candidate["publisher_consistency"] == "consistent"
    assert candidate["certificate_organization"] == "Example Software Ltd."
    assert candidate["evidence_confidence_score"] >= 80
    assert candidate["resource_impact_score"] > 0
    assert candidate["review_priority_score"] > 0
    assert candidate["visible_window_sample_pct"] == 0
    assert candidate["requires_user_intent"] is True
    assert "no stop/disable action is implied" in candidate["recommendation"]
    noted = components._process_candidate(_process_summary(), {"note": "Required for touchpad hotkeys"}, [])
    assert noted["operator_note"] == "Required for touchpad hotkeys"


@pytest.mark.parametrize("kwargs", [
    {"signature": "NotSigned"},
    {"publisher": ""},
    {"protected": 1},
    {"samples": 30},
    {"days": 3},
    {"span_hours": 48},
    {"foreground": 0.15},
    {"cpu": 0.01, "memory": 30, "io_rate": 0.01},
])
def test_process_candidate_suppresses_weak_or_user_active_evidence(kwargs):
    assert components._process_candidate(_process_summary(**kwargs), {}, []) is None


def test_component_keep_and_not_needed_preferences_suppress_future_candidates():
    row = _process_summary()
    component_id = row[0]
    assert components._process_candidate(row, {"preference": "keep"}, []) is None
    assert components._process_candidate(row, {"preference": "not_needed"}, []) is None
    note_only = components._process_candidate(row, {
        "preference": "note_only", "note": "Supports vendor touchpad hotkeys",
    }, [])
    assert note_only is not None
    assert note_only["operator_note"] == "Supports vendor touchpad hotkeys"


def test_review_later_preference_snoozes_for_seven_days():
    row = _process_summary()
    assert components._process_candidate(
        row, {"preference": "review_later", "updated_at": time.time()}, []
    ) is None
    assert components._process_candidate(
        row, {"preference": "review_later", "updated_at": time.time() - 8 * 86400}, []
    ) is not None


def test_service_review_candidate_requires_valid_signature_and_dependency_graph():
    candidate = components._service_candidate(_service_summary(), {})
    assert candidate is not None
    assert candidate["start_mode"] == "auto"
    assert candidate["dependencies"] == ["RpcSs"]
    assert candidate["dependents"] == []
    assert candidate["dependent_count"] == 0
    assert candidate["requires_user_intent"] is True
    assert candidate["publisher_consistency"] == "consistent"
    assert candidate["evidence_confidence_score"] >= 60
    assert candidate["ownership_review_score"] == candidate["evidence_confidence_score"]
    assert "not established" in candidate["recommendation"]
    noted = components._service_candidate(_service_summary(), {"note": "Vendor update scheduler for audio console"})
    assert noted["operator_note"] == "Vendor update scheduler for audio console"


@pytest.mark.parametrize("kwargs", [
    {"signature": "NotSigned"},
    {"publisher": ""},
    {"protected": 1},
    {"start_mode": "manual"},
    {"state": "stopped"},
    {"dependents": '["ExampleClient"]'},
    {"samples": 20},
    {"days": 2},
    {"span_hours": 24},
])
def test_service_candidate_never_ranks_protected_or_uncertain_service(kwargs):
    assert components._service_candidate(_service_summary(**kwargs), {}) is None


def test_service_graph_protection_covers_vanguard_windows_and_system_binary():
    assert components._protected_service({"name": "vgc"}, r"C:\Program Files\Riot Vanguard\vgc.exe")
    assert components._protected_service({"name": "ExampleSvc"}, r"C:\Windows\System32\example.exe")
    assert not components._protected_service({"name": "VendorSvc"}, r"C:\Program Files\Vendor\svc.exe")


def test_process_sampler_uses_fixed_allowlisted_metadata_and_bounded_batch(monkeypatch):
    captured = []
    monkeypatch.setattr(core, "IS_WIN", True)
    monkeypatch.setattr(core, "off", lambda _name: False)
    monkeypatch.setattr(core, "STATE", {
        "procs": [{
            "pid": 2100, "create_time": 1700000000.0, "name": "ExampleHelper.exe",
            "exe": r"C:\Program Files\Example\ExampleHelper.exe", "path_state": "present",
            "cpu": 0.8, "mem": 360, "io": 0.3, "foreground": False,
            "visible_windows": 0, "onscreen_windows": 0, "session_id": 1,
            "status": "running",
        }]
    })
    monkeypatch.setattr(components.safeguard, "is_protected_process", lambda *_args: False)
    monkeypatch.setattr(core, "db", lambda sql, args=(), many=False: captured.append((sql, args)) or [])

    count = components.sample_processes(now=1700000300.0)

    assert count == 1
    sample_calls = [(sql, args) for sql, args in captured if "INSERT INTO component_samples" in sql]
    catalog_calls = [(sql, args) for sql, args in captured if "INSERT INTO component_catalog" in sql]
    assert len(sample_calls) == 1 and len(catalog_calls) == 1
    assert len(sample_calls[0][1]) == 12
    assert "username" not in catalog_calls[0][0]
    assert "exe" not in catalog_calls[0][0]
    assert r"C:\Program Files\Example" not in str(catalog_calls[0][1])


def test_operator_preference_is_persisted_and_clear_is_explicit(monkeypatch):
    statements = []

    def fake_db(sql, args=(), many=False):
        statements.append((sql, args))
        if "SELECT component_type,name FROM component_catalog" in sql:
            return [("process", "Example Helper")]
        return []

    monkeypatch.setattr(core, "db", fake_db)
    monkeypatch.setattr(core, "log", lambda *_args, **_kwargs: None)

    saved = components.set_preference("process:" + "a" * 40, "keep", "Required audio helper")
    assert saved["ok"] is True
    assert saved["preference"] == "keep"
    assert any("INSERT INTO component_preferences" in sql for sql, _args in statements)
    saved_args = next(args for sql, args in statements if "INSERT INTO component_preferences" in sql)
    assert saved_args[2] == "Required audio helper"
    noted = components.set_preference("process:" + "a" * 40, "note_only", "Supports device hotkeys")
    assert noted["preference"] == "note_only"
    noted_args = [args for sql, args in statements if "INSERT INTO component_preferences" in sql][-1]
    assert noted_args[1] == "note_only" and noted_args[2] == "Supports device hotkeys"

    components.set_preference("process:" + "a" * 40, "clear")
    assert any("DELETE FROM component_preferences" in sql for sql, _args in statements)


def test_operator_preference_rejects_unknown_component_and_invalid_state(monkeypatch):
    monkeypatch.setattr(core, "db", lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="keep/not_needed/review_later/note_only/clear"):
        components.set_preference("process:" + "a" * 40, "disable")
    with pytest.raises(ValueError, match="not found"):
        components.set_preference("process:" + "a" * 40, "keep")


def test_component_close_api_only_creates_a_pending_graceful_close_proposal(monkeypatch):
    exe = r"C:\Program Files\Example\ExampleApp.exe"
    component_id = components.process_component_id(exe)
    assert component_id
    monkeypatch.setattr(core, "db", lambda sql, _args=(), many=False: [(0, "Example App")] if "SELECT protected,name" in sql else [])
    monkeypatch.setattr(core, "STATE", {
        "game": None,
        "procs": [{
            "pid": 2200, "create_time": 1700000000.0,
            "name": "ExampleApp.exe", "exe": exe,
            "path_state": "present", "session_id": 1, "visible_windows": 1,
            "onscreen_windows": 1,
        }],
    })
    monkeypatch.setattr(components.safeguard, "is_protected_process", lambda *_args: False)
    captured = {}
    monkeypatch.setattr(actions, "propose", lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs) or 73)

    result = components.propose_graceful_close(component_id)

    assert result["ok"] is True
    assert result["action_id"] == 73
    assert result["requires_confirmation"] is True
    assert captured["args"][0] == "terminate_process"
    assert captured["kwargs"]["origin"] == "component-intelligence"



def test_service_dependency_raw_paths_are_not_persisted(monkeypatch):
    from sentinel import runtime_engine

    raw_path = r"C:\Program Files\ExampleVendor\ServiceHost.exe"
    graph = {
        "services": [{
            "name": "ExampleSvc", "display": "Example Service", "state": "Running",
            "start": "Auto", "pid": 2400, "binary_name": "ServiceHost.exe",
            "binary_path": raw_path, "description": "Service at " + raw_path, "dependencies": ["RpcSs"], "dependents": [],
        }],
        "count": 1, "captured_at": 1700000000.0,
    }
    persisted = {}
    monkeypatch.setattr(core, "IS_WIN", True)
    monkeypatch.setattr(runtime_engine, "admit_optional_work", lambda *_args, **_kwargs: (True, "admitted"))
    monkeypatch.setattr(components, "_service_graph_query", lambda: graph)
    monkeypatch.setattr(components, "_save_state", lambda key, value: persisted.update({key: value}))

    result = components.refresh_service_graph(force=True)

    assert result["ok"] is True
    stored = persisted["service_graph"]
    assert stored["services"][0]["dependencies"] == ["RpcSs"]
    assert stored["services"][0]["dependents"] == []
    assert stored["services"][0]["binary_name"] == "ServiceHost.exe"
    assert "binary_path" not in stored["services"][0]
    assert "description" not in stored["services"][0]
    assert raw_path not in str(stored)


def test_local_ai_evidence_contains_dependency_graph_and_baseline_candidate_ids(monkeypatch):
    rows = [(
        "service:" + "c" * 40, "ExampleSvc", "ExampleSvc.exe", "Example Corp",
        "Valid", "CN=Example Corp", 0, '["RpcSs"]', '[]', "auto", "running",
    )]

    def fake_db(sql, args=(), many=False):
        if "FROM component_catalog WHERE component_type='service'" in sql:
            return rows
        if "FROM component_preferences p JOIN component_catalog c" in sql:
            return [("process:" + "d" * 40, "process", "VendorTray.exe", "Vendor Inc.", "keep", "Required for hotkeys", 1700000000.0)]
        return []

    monkeypatch.setattr(core, "db", fake_db)
    evidence = components.ai_evidence()

    assert len(evidence["service_dependency_graph"]) == 1
    graph_row = evidence["service_dependency_graph"][0]
    assert graph_row["id"] == "component-service-graph.1"
    assert graph_row["dependencies"] == ["RpcSs"]
    assert graph_row["publisher_consistency"] == "consistent"
    assert "binary_path" not in str(evidence)
    assert evidence["operator_component_preferences"][0]["preference"] == "keep"
    assert evidence["operator_component_preferences"][0]["operator_note"] == "Required for hotkeys"
    assert evidence["component_score_semantics"]["evidence_confidence_score"].startswith("0-100 measurement coverage")
    assert "not a probability" in evidence["component_score_semantics"]["evidence_confidence_score"]



@pytest.mark.parametrize("kwargs", [
    {"visible_ratio": 0.08},
    {"onscreen_ratio": 0.03},
])
def test_process_candidate_rejects_historically_visible_gui_apps(kwargs):
    assert components._process_candidate(_process_summary(**kwargs), {}, []) is None


def test_process_candidate_exposes_metadata_vs_certificate_identity_mismatch():
    candidate = components._process_candidate(
        _process_summary(publisher="Example Helper Corporation", signer="CN=Different Signing LLC"),
        {}, [],
    )
    assert candidate is not None
    assert candidate["publisher_consistency"] == "different"
    assert candidate["evidence_confidence_score"] < 85
    assert candidate["certificate_organization"] == "Different Signing LLC"


def test_publisher_identity_prefers_certificate_organization_over_file_metadata():
    assert components._certificate_organization(
        "CN=Example Signing Certificate, O=Example Software Ltd., C=US"
    ) == "Example Software Ltd."
    assert components._publisher_consistency(
        "Example Software Ltd.", "CN=Example Signing Certificate, O=Example Software Ltd., C=US"
    ) == "consistent"
    assert components._publisher_consistency("File Company", "CN=Signing Entity") == "different"
    assert components._publisher_consistency("", "CN=Signing Entity") == "unknown"


def test_baseline_confidence_is_a_measurement_coverage_score_not_usefulness_probability():
    assert components._baseline_confidence(900, 14, 336, "Valid", "consistent") == 100.0
    partial = components._baseline_confidence(120, 7, 168, "Valid", "consistent")
    assert 50 <= partial < 60
    assert components._baseline_confidence(900, 14, 336, "Valid", "different") < 100



def test_component_candidate_close_requires_one_unambiguous_gui_instance(monkeypatch):
    exe = r"C:\Program Files\Example\ExampleApp.exe"
    component_id = components.process_component_id(exe)
    monkeypatch.setattr(components.safeguard, "is_protected_process", lambda *_args: False)
    first = {
        "pid": 301, "create_time": 1700000000.0, "name": "ExampleApp.exe", "exe": exe,
        "path_state": "present", "session_id": 1, "visible_windows": 1, "onscreen_windows": 1,
    }
    second = {**first, "pid": 302, "create_time": 1700000010.0}
    assert components._current_interactive_instance(component_id, [first]) is first
    assert components._current_interactive_instance(component_id, [first, second]) is None


def test_component_score_semantics_distinguish_resource_impact_and_service_ownership(monkeypatch):
    monkeypatch.setattr(components, "ensure_schema", lambda: None)
    monkeypatch.setattr(components, "_preference_map", lambda: {})
    monkeypatch.setattr(components, "_aggregate_rows", lambda _kind, _since: [])
    monkeypatch.setattr(components, "_load_state", lambda _key: {})
    monkeypatch.setattr(components, "_last_sample", lambda _kind: 0.0)
    monkeypatch.setattr(core, "STATE", {})
    report = components.report()
    semantics = report["score_semantics"]
    assert "not a probability" in semantics["evidence_confidence_score"]
    assert "weighted 35/45/20" in semantics["resource_impact_score"]
    assert "sorting heuristic" in semantics["review_priority_score"]
    assert "no service resource-impact score" in semantics["ownership_review_score"]


def test_process_sampling_pauses_during_game_sessions(monkeypatch):
    monkeypatch.setattr(components, "ensure_schema", lambda: None)
    monkeypatch.setattr(core, "IS_WIN", True)
    monkeypatch.setattr(core, "STATE", {"game": {"name": "VALORANT"}, "procs": []})
    monkeypatch.setattr(core, "off", lambda _name: False)
    assert components.sample_processes() == 0



@pytest.mark.parametrize("graph_age_hours,expected_candidates", [
    (None, 0),
    (25, 0),
    (12, 1),
])
def test_service_ownership_candidates_require_a_complete_recent_graph(monkeypatch, graph_age_hours, expected_candidates):
    monkeypatch.setattr(components, "ensure_schema", lambda: None)
    monkeypatch.setattr(components, "_preference_map", lambda: {})
    monkeypatch.setattr(components, "_aggregate_rows", lambda kind, _since: (
        [_service_summary()] if kind == "service" else []
    ))
    graph = {} if graph_age_hours is None else {
        "count": 200, "captured_at": time.time() - graph_age_hours * 3600,
    }
    monkeypatch.setattr(components, "_load_state", lambda key: graph if key == "service_graph" else {})
    monkeypatch.setattr(components, "_last_sample", lambda _kind: 0.0)
    monkeypatch.setattr(core, "STATE", {})

    result = components.report()

    assert len(result["service_candidates"]) == expected_candidates
    assert result["coverage"]["service_dependency_graph_fresh"] is (expected_candidates == 1)
    if expected_candidates == 0:
        assert "newer than 24 hours" in result["service_review_block_reason"]
