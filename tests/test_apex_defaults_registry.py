from apex.config import ApexSettings
from apex.tools.defaults import build_default_registry

def test_default_registry_builds_without_shadowing_settings_provider():
    registry = build_default_registry(runtime_settings=ApexSettings())
    names = {item["name"] for item in registry.manifest()}
    assert "apex_open_settings" in names
    assert "apex_open_management_console" in names
    assert "apex_set_master_mute" in names


def test_phase_one_everyday_windows_capabilities_are_registered():
    registry = build_default_registry(runtime_settings=ApexSettings())
    names = {item["name"] for item in registry.manifest()}
    assert {
        "apex_get_process_details",
        "apex_set_network_adapter_enabled",
        "apex_dhcp_lease_action",
        "apex_set_service_start_type",
        "apex_media_control",
        "apex_drag_drop",
    }.issubset(names)
    # Process termination remains deliberately unregistered until an independently reviewed,
    # reversible process-control policy and dedicated approval surface exist.
    assert "apex_terminate_process" not in names


def test_phase_one_extended_windows_capabilities_are_registered():
    registry = build_default_registry(runtime_settings=ApexSettings())
    names = {item["name"] for item in registry.manifest()}
    assert {
        "apex_type_text",
        "apex_drag_drop",
        "apex_get_process_details",
        "apex_set_network_adapter_enabled",
        "apex_dhcp_lease_action",
        "apex_set_service_start_type",
        "apex_media_control",
    }.issubset(names)


def test_registry_tool_ids_are_unique():
    registry = build_default_registry(runtime_settings=ApexSettings())
    ids = [item["name"] for item in registry.manifest()]
    assert len(ids) == len(set(ids))
