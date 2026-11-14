import os

import pytest

from senti.config import SentiSettings
from senti.tools.defaults import build_default_registry
from senti.windows import settings, settings_catalog

OPEN_TOOLS = ("senti_open_windows_surface", "senti_open_settings", "senti_open_control_panel",
              "senti_open_management_console")


@pytest.fixture()
def launches(monkeypatch):
    calls = []
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)
    monkeypatch.setattr(settings, "get_windows_build", lambda: 26300)
    monkeypatch.setattr(settings, "surface_catalog",
                        lambda include_discovered=True: settings_catalog.STATIC_SURFACES)
    monkeypatch.setattr(settings, "provider_available", lambda: True)
    return calls


def _base(path):
    return os.path.basename(path).lower()


def test_every_opening_tool_has_a_provider_simulation():
    registry = build_default_registry(runtime_settings=SentiSettings())
    manifest = {row["name"]: row for row in registry.manifest()}
    for name in OPEN_TOOLS:
        assert manifest[name]["simulation"] == "provider", name
    assert manifest["senti_open_management_console"]["risk"] == "controlled"
    assert manifest["senti_open_windows_surface"]["risk"] == "low"
    for name in (*OPEN_TOOLS, "senti_search_windows_surfaces"):
        schema = registry.tool(name).parameters
        assert schema["additionalProperties"] is False
        assert "enum" not in schema["properties"].get("target", {})


@pytest.mark.parametrize(("tool", "target"), [
    ("senti_open_windows_surface", "bluetooth"),
    ("senti_open_windows_surface", "clsid_god_mode"),
    ("senti_open_settings", "Wi-Fi settings"),
    ("senti_open_control_panel", "cpl_sysdm_advanced"),
    ("senti_open_management_console", "util_regedit"),
])
def test_simulate_never_launches(launches, tool, target):
    registry = build_default_registry(runtime_settings=SentiSettings())
    preview = registry.simulate(tool, {"target": target})
    assert preview["valid"] is True, preview
    assert preview["simulation"] == "provider"
    assert "no settings are changed" in preview["effect"]
    assert preview["changes_settings"] is False
    assert preview["launch"]["file"]
    assert launches == []


def test_simulate_reports_unknown_targets_as_invalid(launches):
    registry = build_default_registry(runtime_settings=SentiSettings())
    preview = registry.simulate("senti_open_windows_surface", {"target": "cmd.exe /c whoami"})
    assert preview["valid"] is False
    assert launches == []


def test_simulate_preview_shape(launches):
    preview = settings.simulate_open("bluetooth")
    assert preview["target"] == "ms-settings:bluetooth"
    assert preview["kind"] == "ms_settings"
    assert preview["title"] == "Bluetooth"
    assert preview["present"] == "unknown"
    assert launches == []


@pytest.mark.parametrize("target", [
    "cmd.exe /c whoami", "ms-settings:bluetooth?x=1", "ms-settings:anything-made-up",
    r"C:\Windows\System32\cmd.exe", "shell:::{00000000-0000-0000-0000-000000000000}",
    "shell:..\\..\\Windows", "powershell", "regedit.exe /s evil.reg", "blutooth",
])
def test_launching_rejects_unknown_or_free_form_targets(launches, target):
    with pytest.raises(ValueError):
        settings.open_windows_surface(target)
    assert launches == []


def test_controlled_consoles_need_the_controlled_tool(launches):
    with pytest.raises(ValueError, match="senti_open_management_console"):
        settings.open_windows_surface("util_regedit")
    assert launches == []
    result = settings.open_console("util_regedit")
    (args, kwargs), = launches
    assert _base(args[0]) == "regedit.exe" and kwargs == {}
    assert result["target"] == "util_regedit"


def test_launch_specs_use_absolute_executables_and_fixed_arguments(launches):
    settings.open_windows_surface("cpl_sysdm_advanced")
    settings.open_windows_surface("cp_power_buttons")
    settings.open_windows_surface("shell_downloads")
    settings.open_windows_surface("clsid_god_mode")
    settings.open_windows_surface("util_environment_variables")
    settings.open_windows_surface("msc_eventvwr")
    rendered = [(_base(args[0]), kwargs.get("arguments")) for args, kwargs in launches]
    assert rendered == [
        ("control.exe", "sysdm.cpl,,3"),
        ("control.exe", "/name Microsoft.PowerOptions /page pageGlobalSettings"),
        ("explorer.exe", "shell:Downloads"),
        ("explorer.exe", "shell:::{ED7BA470-8E54-465E-825C-99712043E01C}"),
        ("rundll32.exe", "sysdm.cpl,EditEnvironmentVariables"),
        ("eventvwr.msc", None),
    ]
    assert all(os.path.isabs(args[0]) for args, _kwargs in launches)


def test_entries_known_to_be_absent_are_not_launched(launches, monkeypatch):
    absent = [dict(item, present=False) if item["id"] == "msc_gpedit" else item
              for item in settings_catalog.STATIC_SURFACES]
    monkeypatch.setattr(settings, "surface_catalog", lambda include_discovered=True: absent)
    with pytest.raises(ValueError, match="not found on this PC"):
        settings.open_console("msc_gpedit")
    assert launches == []


def test_discovered_entries_launch_from_their_verified_path(launches, monkeypatch, tmp_path):
    console = tmp_path / "vendor.msc"
    console.write_text("x")
    discovered = settings_catalog._entry(
        id="msc_vendor", kind="msc", category="Management consoles", title="vendor (vendor.msc)",
        target="vendor.msc", file="vendor.msc", path=str(console), risk="controlled",
        source="discovered", present=True)
    entries = [*settings_catalog.STATIC_SURFACES, discovered]
    monkeypatch.setattr(settings, "surface_catalog", lambda include_discovered=True: entries)
    settings.open_console("msc_vendor")
    assert launches == [((str(console),), {})]


def test_ambiguous_names_are_not_guessed(launches):
    with pytest.raises(ValueError, match="ambiguous"):
        settings.open_windows_surface("Device Manager")
    assert launches == []


def test_search_windows_surfaces_returns_ranked_candidates(launches):
    result = settings.search_windows_surfaces("device manager", limit=5)
    assert result["mode"] == "ranked"
    top = result["candidates"][0]
    assert top["id"] in {"msc_devmgmt", "cp_device_manager", "cpl_hdwwiz"}
    assert {"score", "kind", "risk", "present", "source", "open_with"}.issubset(top)
    regedit = settings.search_windows_surfaces("registry editor", limit=3)["candidates"][0]
    assert regedit["open_with"] == "senti_open_management_console"


def test_search_windows_surfaces_lists_with_pagination(launches):
    first = settings.search_windows_surfaces("", kind="msc", limit=10)
    second = settings.search_windows_surfaces("", kind="msc", limit=10, offset=10)
    assert first["mode"] == "listing" and first["count"] == 10
    assert first["next_offset"] == 10
    assert {c["id"] for c in first["candidates"]}.isdisjoint({c["id"] for c in second["candidates"]})
    assert all(c["kind"] == "msc" for c in first["candidates"] + second["candidates"])


def test_search_windows_surfaces_validates_kind(launches):
    with pytest.raises(ValueError):
        settings.search_windows_surfaces("x", kind="powershell")
