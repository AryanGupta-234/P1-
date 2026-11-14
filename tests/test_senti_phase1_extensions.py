from senti.config import SentiSettings
from senti.runtime import SentiHost
from senti.store import UnifiedDataStore


def test_host_registers_phase1_tools_and_persists_emergency_stop(tmp_path):
    path = tmp_path / "senti.sqlite3"
    store = UnifiedDataStore(path)
    host = SentiHost(settings=SentiSettings(auto_start_ollama=False), ollama=object(), store=store)

    tool_names = {item["name"] for item in host.registry.manifest()}
    assert {
        "senti_list_power_plans",
        "senti_set_power_plan",
        "senti_get_windows_security_status",
        "senti_get_windows_update_status",
        "senti_search_memory",
        "senti_save_memory",
        "senti_forget_memory",
        "senti_uia_wait_for",
        "senti_get_runtime_manifest",
        "senti_list_wireless_radios",
        "senti_set_wifi_radio",
    }.issubset(tool_names)

    result = host.set_emergency_stop(True, reason="test")
    assert result == {
        "emergency_stop": True,
        "mutations_enabled": False,
        "persisted": True,
    }

    restarted = SentiHost(
        settings=SentiSettings(auto_start_ollama=False),
        ollama=object(),
        store=UnifiedDataStore(path),
    )
    assert restarted.registry.mutations_enabled is False
    assert restarted.runtime_manifest()["policy"]["emergency_stop"] is True



def test_runtime_manifest_tool_returns_compact_host_authoritative_inventory(tmp_path):
    host = SentiHost(
        settings=SentiSettings(auto_start_ollama=False),
        ollama=object(),
        store=UnifiedDataStore(tmp_path / "manifest.sqlite3"),
    )

    result = host.registry.dispatch("senti_get_runtime_manifest", {})

    assert result.status == "succeeded"
    assert result.data["manifest"]["think_mode"] == "auto"
    assert "installed_local_models" in result.data["manifest"]
    capabilities = result.data["manifest"]["capabilities"]
    assert any(item["name"] == "senti_get_process_details" for item in capabilities)
    assert all("description" not in item for item in capabilities)
