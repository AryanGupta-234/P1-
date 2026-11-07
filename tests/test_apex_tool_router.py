from apex.tools.defaults import build_default_registry
from apex.tools.router import select_tool_schemas


def test_router_selects_network_tools_for_wifi_and_dns_question():
    registry = build_default_registry()
    schemas = registry.definitions(available_only=False)

    selected = select_tool_schemas("Check my Wi-Fi adapter and DNS configuration", schemas)

    names = {item["function"]["name"] for item in selected}
    assert "apex_list_network_configurations" in names
    assert "apex_set_dns_servers" in names
    assert "apex_list_processes" not in names
    assert len(selected) <= 18


def test_router_expands_running_process_synonym():
    registry = build_default_registry()
    schemas = registry.definitions(available_only=False)

    selected = select_tool_schemas("What is currently running?", schemas)

    names = {item["function"]["name"] for item in selected}
    assert "apex_list_processes" in names
    assert "apex_get_process_details" in names


def test_router_does_not_send_irrelevant_tools_for_general_chat():
    registry = build_default_registry()
    schemas = registry.definitions(available_only=False)

    assert select_tool_schemas("Tell me a joke about penguins", schemas) == []


def test_router_is_bounded_and_validates_inputs():
    registry = build_default_registry()
    schemas = registry.definitions(available_only=False)

    try:
        select_tool_schemas("processes", schemas, limit=0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid schema limit was accepted")

    try:
        select_tool_schemas("x" * 12_001, schemas)
    except ValueError:
        pass
    else:
        raise AssertionError("oversized route query was accepted")



def test_router_maps_common_pc_spec_language_to_system_summary():
    registry = build_default_registry()
    schemas = registry.definitions(available_only=False)

    selected = select_tool_schemas("What specs does my PC have?", schemas)

    names = {item["function"]["name"] for item in selected}
    assert "apex_get_system_summary" in names



def test_router_maps_remember_and_notes_language_to_memory_tools():
    from apex.tools.phase1_tools import register_phase1_tools
    from apex.store import UnifiedDataStore

    registry = build_default_registry()
    register_phase1_tools(registry, UnifiedDataStore(":memory:"))
    schemas = registry.definitions(available_only=False)

    save_names = {item["function"]["name"] for item in select_tool_schemas(
        "Please remember my preference for concise answers", schemas
    )}
    search_names = {item["function"]["name"] for item in select_tool_schemas(
        "Search my saved notes about APEX", schemas
    )}

    assert "apex_save_memory" in save_names
    assert "apex_search_memory" in search_names
