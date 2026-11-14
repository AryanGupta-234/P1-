from senti.tools.registry import CapabilityRegistry, ToolDefinition

def test_non_read_only_tool_requires_host_approval():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_change", "change", {"type": "object"}, "controlled",
                                     lambda _args: {"summary": "changed"}))
    denied = registry.dispatch("senti_change", {})
    assert denied.status == "approval_required"
    approved = registry.dispatch("senti_change", {}, approval=lambda *_args: True)
    assert approved.status == "succeeded"

def test_unregistered_tool_is_denied():
    registry = CapabilityRegistry()
    assert registry.dispatch("senti_execute_shell", {}).status == "denied"

def test_tool_schema_rejects_unknown_arguments_and_type_confusion():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_volume", "set volume", {
        "type": "object", "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["volume"], "additionalProperties": False,
    }, "controlled", lambda args: {"summary": f"set {args['volume']}"}))
    assert registry.dispatch("senti_volume", {"volume": True}, approval=lambda *_: True).status == "denied"
    assert registry.dispatch("senti_volume", {"volume": 20, "command": "whoami"}, approval=lambda *_: True).status == "denied"
    assert registry.dispatch("senti_volume", {"volume": 20}, approval=lambda *_: True).status == "succeeded"

def test_tool_rate_limit_is_enforced():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_probe", "probe", {"type": "object"}, "read_only",
                                     lambda _args: {"summary": "ok"}, max_per_minute=1))
    assert registry.dispatch("senti_probe", {}).status == "succeeded"
    assert registry.dispatch("senti_probe", {}).status == "denied"



def test_registry_manifest_exposes_schema_and_policy_metadata():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition(
        "senti_read", "read", {"type": "object", "properties": {}}, "read_only",
        lambda _args: {"summary": "ok"}, max_per_minute=4,
    ))
    registry.register(ToolDefinition(
        "senti_change", "change", {"type": "object", "properties": {}}, "controlled",
        lambda _args: {"summary": "changed"},
    ))

    rows = {item["name"]: item for item in registry.manifest()}
    assert rows["senti_read"]["schema_version"] == 1
    assert rows["senti_read"]["execution_context"] == "current_user"
    assert rows["senti_read"]["approval_required"] is False
    assert rows["senti_read"]["rate_limit_per_minute"] == 4
    assert rows["senti_change"]["approval_required"] is True
    assert rows["senti_change"]["mutations_enabled"] is True


def test_tool_definition_rejects_unsupported_execution_context():
    try:
        ToolDefinition(
            "senti_bad", "bad", {"type": "object"}, "controlled",
            lambda _args: {"summary": "bad"}, execution_context="administrator",
        )
    except ValueError as exc:
        assert "current user context" in str(exc)
    else:
        raise AssertionError("unsupported execution context was accepted")
