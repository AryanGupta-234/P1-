from apex.tools.registry import CapabilityRegistry, ToolDefinition


def test_emergency_stop_blocks_mutating_capabilities_but_not_read_only():
    registry = CapabilityRegistry()
    registry.register(ToolDefinition(
        "apex_read", "read", {"type": "object"}, "read_only",
        lambda _args: {"summary": "read"},
    ))
    registry.register(ToolDefinition(
        "apex_mutate", "mutate", {"type": "object"}, "controlled",
        lambda _args: {"summary": "mutated"},
    ))

    registry.set_mutations_enabled(False)
    assert registry.dispatch("apex_read", {}).status == "succeeded"
    blocked = registry.dispatch("apex_mutate", {}, approval=lambda *_args: True)
    assert blocked.status == "denied"
    assert "emergency stop" in blocked.summary.lower()

    registry.set_mutations_enabled(True)
    approved = registry.dispatch("apex_mutate", {}, approval=lambda *_args: True)
    assert approved.status == "succeeded"


def test_emergency_stop_requires_boolean():
    registry = CapabilityRegistry()
    try:
        registry.set_mutations_enabled("false")
    except ValueError:
        pass
    else:
        raise AssertionError("non-boolean emergency stop value was accepted")
