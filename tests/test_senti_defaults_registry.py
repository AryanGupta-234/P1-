from senti.config import SentiSettings
from senti.tools.defaults import build_default_registry

def test_default_registry_builds_without_shadowing_settings_provider():
    registry = build_default_registry(runtime_settings=SentiSettings())
    names = {item["name"] for item in registry.manifest()}
    assert "senti_open_settings" in names
    assert "senti_open_management_console" in names
    assert "senti_set_master_mute" in names


def test_phase_one_everyday_windows_capabilities_are_registered():
    registry = build_default_registry(runtime_settings=SentiSettings())
    names = {item["name"] for item in registry.manifest()}
    assert {
        "senti_get_process_details",
        "senti_set_network_adapter_enabled",
        "senti_dhcp_lease_action",
        "senti_set_service_start_type",
        "senti_media_control",
        "senti_drag_drop",
    }.issubset(names)
    # Process termination remains deliberately unregistered until an independently reviewed,
    # reversible process-control policy and dedicated approval surface exist.
    assert "senti_terminate_process" not in names


def test_phase_one_extended_windows_capabilities_are_registered():
    registry = build_default_registry(runtime_settings=SentiSettings())
    names = {item["name"] for item in registry.manifest()}
    assert {
        "senti_type_text",
        "senti_drag_drop",
        "senti_get_process_details",
        "senti_set_network_adapter_enabled",
        "senti_dhcp_lease_action",
        "senti_set_service_start_type",
        "senti_media_control",
    }.issubset(names)


def test_registry_tool_ids_are_unique():
    registry = build_default_registry(runtime_settings=SentiSettings())
    ids = [item["name"] for item in registry.manifest()]
    assert len(ids) == len(set(ids))



def test_settings_catalogue_tools_are_registered_without_a_huge_uri_enum():
    registry = build_default_registry(runtime_settings=SentiSettings())
    rows = {item["name"]: item for item in registry.manifest()}

    assert {
        "senti_open_settings",
        "senti_search_settings_pages",
        "senti_list_settings_pages",
        "senti_open_control_panel",
    }.issubset(rows)

    open_schema = next(
        item for item in registry.definitions(available_only=False)
        if item["function"]["name"] == "senti_open_settings"
    )
    target_schema = open_schema["function"]["parameters"]["properties"]["target"]
    assert target_schema["type"] == "string"
    assert "enum" not in target_schema
