from senti.config import SentiSettings
from senti.tools.app_tools import UNINSTALL_COMPENSATION, register_app_tools
from senti.tools.defaults import build_default_registry
from senti.windows import uninstall


def _registry():
    registry = build_default_registry(runtime_settings=SentiSettings())
    register_app_tools(registry)
    return registry


def test_app_tools_register_without_duplicates_and_with_strict_schemas():
    registry = _registry()
    names = ["senti_list_installed_software", "senti_find_application", "senti_launch_application",
             "senti_uninstall_application"]
    for name in names:
        tool = registry.tool(name)
        assert tool is not None
        assert tool.parameters["additionalProperties"] is False
    assert registry.tool("senti_list_installed_software").risk == "read_only"
    assert registry.tool("senti_find_application").risk == "read_only"
    remove = registry.tool("senti_uninstall_application")
    assert remove.risk == "high" and remove.simulate is not None
    assert remove.compensation == UNINSTALL_COMPENSATION and remove.max_per_minute <= 3
    assert registry.tool("senti_launch_application").simulate is not None


def test_uninstall_requires_a_target_and_never_runs_without_approval(monkeypatch):
    registry = _registry()
    monkeypatch.setattr(uninstall, "uninstall", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    preview = registry.simulate("senti_uninstall_application", {})
    assert preview["valid"] is False
    result = registry.dispatch("senti_uninstall_application", {"application": "anything"})
    assert result.status in {"approval_required", "unavailable"}


def test_uninstall_simulation_through_registry_uses_provider(monkeypatch):
    registry = _registry()
    monkeypatch.setattr(uninstall, "simulate_uninstall", lambda args: {
        "name": "Contoso", "command": "msiexec.exe /x {G}", "executes": False})
    preview = registry.simulate("senti_uninstall_application", {"application": "contoso"})
    if preview["available"]:
        assert preview["simulation"] == "provider" and preview["command"] == "msiexec.exe /x {G}"
        assert preview["recovery"] == UNINSTALL_COMPENSATION
