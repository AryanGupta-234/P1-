from apex.config import ApexSettings
from apex.runtime import ApexHost
from apex.store import UnifiedDataStore


def test_host_registers_phase1_tools_and_persists_emergency_stop(tmp_path):
    path = tmp_path / "apex.sqlite3"
    store = UnifiedDataStore(path)
    host = ApexHost(settings=ApexSettings(auto_start_ollama=False), ollama=object(), store=store)

    tool_names = {item["name"] for item in host.registry.manifest()}
    assert {
        "apex_list_power_plans",
        "apex_set_power_plan",
        "apex_get_windows_security_status",
        "apex_get_windows_update_status",
        "apex_search_memory",
        "apex_save_memory",
        "apex_forget_memory",
        "apex_uia_wait_for",
    }.issubset(tool_names)

    result = host.set_emergency_stop(True, reason="test")
    assert result == {
        "emergency_stop": True,
        "mutations_enabled": False,
        "persisted": True,
    }

    restarted = ApexHost(
        settings=ApexSettings(auto_start_ollama=False),
        ollama=object(),
        store=UnifiedDataStore(path),
    )
    assert restarted.registry.mutations_enabled is False
    assert restarted.runtime_manifest()["policy"]["emergency_stop"] is True
