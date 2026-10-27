from sentinel import core, workflow_engine


def test_workflow_trigger_schemas_are_typed_and_bounded():
    assert workflow_engine._validate_trigger("event", {"category": "application_crash"}) == {
        "category": "application_crash"
    }
    assert workflow_engine._validate_trigger("schedule", {"interval_hours": 24}) == {
        "interval_hours": 24
    }
    metric = workflow_engine._validate_trigger("metric", {
        "metric": "cpu", "operator": "above", "threshold": 92, "consecutive_samples": 3,
    })
    assert metric["threshold"] == 92.0
    assert metric["consecutive_samples"] == 3


def test_workflow_trigger_rejects_unbounded_or_unknown_conditions():
    import pytest

    with pytest.raises(ValueError, match="supported Windows fault category"):
        workflow_engine._validate_trigger("event", {"category": "any_event"})
    with pytest.raises(ValueError, match="6, 12, 24"):
        workflow_engine._validate_trigger("schedule", {"interval_hours": 1})
    with pytest.raises(ValueError, match="allowlisted metric"):
        workflow_engine._validate_trigger("metric", {
            "metric": "disk_serial", "operator": "above", "threshold": 10, "consecutive_samples": 3,
        })
    with pytest.raises(ValueError, match="above operator"):
        workflow_engine._validate_trigger("metric", {
            "metric": "cpu", "operator": "below", "threshold": 10, "consecutive_samples": 3,
        })


def test_workflow_actions_reject_shell_commands_and_unknown_payload_fields():
    import pytest

    assert workflow_engine._validate_action("local_ai_review", {}) == {}
    assert workflow_engine._validate_action("storage_scan", {}) == {}
    assert workflow_engine._validate_action("notify_user", {"message": "Crash detected"}) == {
        "message": "Crash detected"
    }
    with pytest.raises(ValueError, match="takes no parameters"):
        workflow_engine._validate_action("local_ai_review", {"command": "powershell.exe"})
    with pytest.raises(ValueError, match="unsupported action"):
        workflow_engine._validate_action("run_powershell", {"script": "Stop-Service vgc"})


def test_windows_event_categories_are_specific():
    assert workflow_engine._event_category("eventlog", "Application Error Event ID 1000") == "application_crash"
    assert workflow_engine._event_category("eventlog", "WHEA hardware error") == "hardware_error"
    assert workflow_engine._event_category("eventlog", "Kernel-PnP device cannot start") == "driver_error"
    assert workflow_engine._event_category("eventlog", "Disk/storage error NTFS") == "disk_error"
    assert workflow_engine._event_category("WindowsUpdateClient", "Installation failure") == "windows_update"
    assert workflow_engine._event_category("unknown", "Routine informational message") is None


def test_new_event_flow_starts_at_current_event_cursor(monkeypatch):
    inserted = {}
    row = (
        41, "Crash → AI review", 1, "event", '{"category":"application_crash"}',
        "local_ai_review", "{}", 1800, 0, 900, 0, 1000.0, 1000.0,
    )

    def fake_db(sql, args=(), many=False):
        if "SELECT COALESCE(MAX(id),0) FROM events" in sql:
            return [(900,)]
        if "FROM automation_flows WHERE id=?" in sql:
            return [row]
        if "FROM automation_runs WHERE flow_id=?" in sql:
            return []
        return []

    def fake_insert(sql, args=()):
        inserted["sql"] = sql
        inserted["args"] = args
        return 41

    monkeypatch.setattr(core, "db", fake_db)
    monkeypatch.setattr(core, "insert_id", fake_insert)
    monkeypatch.setattr(core, "log", lambda *args, **kwargs: None)
    flow = workflow_engine.create_flow({
        "name": "Crash → AI review", "enabled": True,
        "trigger_type": "event", "trigger": {"category": "application_crash"},
        "action_type": "local_ai_review", "action": {}, "cooldown_minutes": 30,
    })
    assert flow["id"] == 41
    assert inserted["args"][7] == 900
    assert flow["trigger"]["category"] == "application_crash"
    assert flow["action_type"] == "local_ai_review"


def test_workflow_has_no_direct_windows_mutation_action_surface():
    assert workflow_engine.ACTIONS == {
        "local_ai_review", "read_only_diagnostics", "storage_scan", "notify_user"
    }
    source = open(workflow_engine.__file__, encoding="utf-8").read()
    assert "arbitrary commands and scripts are not accepted" in source
    assert "maintenance mutations require separate preview and approval" in source
    assert "core.thread(_loop" not in source
