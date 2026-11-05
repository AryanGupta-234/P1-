from apex.tools.registry import CapabilityRegistry, ToolDefinition

def test_non_read_only_tool_requires_host_approval():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("apex_change", "change", {"type": "object"}, "controlled",
                                     lambda _args: {"summary": "changed"}))
    denied = registry.dispatch("apex_change", {})
    assert denied.status == "approval_required"
    approved = registry.dispatch("apex_change", {}, approval=lambda *_args: True)
    assert approved.status == "succeeded"

def test_unregistered_tool_is_denied():
    registry = CapabilityRegistry()
    assert registry.dispatch("apex_execute_shell", {}).status == "denied"

def test_tool_schema_rejects_unknown_arguments_and_type_confusion():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("apex_volume", "set volume", {
        "type": "object", "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["volume"], "additionalProperties": False,
    }, "controlled", lambda args: {"summary": f"set {args['volume']}"}))
    assert registry.dispatch("apex_volume", {"volume": True}, approval=lambda *_: True).status == "denied"
    assert registry.dispatch("apex_volume", {"volume": 20, "command": "whoami"}, approval=lambda *_: True).status == "denied"
    assert registry.dispatch("apex_volume", {"volume": 20}, approval=lambda *_: True).status == "succeeded"

def test_tool_rate_limit_is_enforced():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("apex_probe", "probe", {"type": "object"}, "read_only",
                                     lambda _args: {"summary": "ok"}, max_per_minute=1))
    assert registry.dispatch("apex_probe", {}).status == "succeeded"
    assert registry.dispatch("apex_probe", {}).status == "denied"
