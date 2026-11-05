from apex.config import ApexSettings
from apex.tools.defaults import build_default_registry

def test_default_registry_builds_without_shadowing_settings_provider():
    registry = build_default_registry(runtime_settings=ApexSettings())
    names = {item["name"] for item in registry.manifest()}
    assert "apex_open_settings" in names
    assert "apex_open_management_console" in names
    assert "apex_set_master_mute" in names
