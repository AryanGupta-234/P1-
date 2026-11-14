import os
import re

import pytest

from senti.windows import settings, settings_catalog


def _static(monkeypatch):
    """Keep launcher tests deterministic: no live discovery."""
    monkeypatch.setattr(settings, "surface_catalog", lambda include_discovered=True: settings_catalog.STATIC_SURFACES)


# ------------------------------------------------------------------ catalogue integrity

def test_catalogue_is_broad_and_ids_are_unique():
    entries = settings_catalog.STATIC_SURFACES
    identifiers = [item["id"] for item in entries]
    assert len(identifiers) >= 350
    assert len(identifiers) == len(set(identifiers))
    counts = settings_catalog.catalogue_counts()
    assert counts["ms_settings"] >= 230
    assert counts["control_name"] >= 50
    assert counts["cpl"] >= 25
    assert counts["msc"] >= 20
    assert counts["utility"] >= 50
    assert counts["shell_folder"] >= 50
    assert counts["shell_clsid"] >= 10


def test_every_entry_has_valid_kind_risk_lifecycle_and_structured_target():
    for item in settings_catalog.STATIC_SURFACES:
        assert item["kind"] in settings_catalog.KINDS
        assert item["risk"] in {"low", "controlled"}
        assert item["lifecycle"] in settings_catalog.LIFECYCLES
        assert item["title"] and item["category"]
        assert isinstance(item["aliases"], list)
        assert item["source"] == "static"
        assert item["present"] in {"unknown", False}
        settings_catalog.validate_entry(item)  # raises on free-form targets


def test_settings_only_view_stays_compatible():
    assert len(settings_catalog.SETTINGS_CATALOG) >= 180
    assert all(item["uri"].startswith("ms-settings:") for item in settings_catalog.SETTINGS_CATALOG)
    assert {
        "Accounts", "Apps", "Devices", "Accessibility", "Gaming", "Network and internet",
        "Personalization", "Privacy", "Sound", "System", "Time and language", "Update and security",
    }.issubset({item["category"] for item in settings_catalog.SETTINGS_CATALOG})


@pytest.mark.parametrize("target", [
    "ms-settings:workplace-provisioning", "ms-settings:holographic-headset", "ms-settings:developers",
    "ms-settings:sound-devices", "ms-settings:nightlight", "ms-settings:apps-volume",
    "ms-settings:privacy-webcam", "ms-settings:regionlanguage-adddisplaylanguage", "ms-settings:",
    "Microsoft.DeviceManager", "Microsoft.PowerOptions /page pageGlobalSettings", "sysdm.cpl,,3",
    "inetcpl.cpl,,4", "mmsys.cpl,,1", "devmgmt.msc", "gpedit.msc", "wf.msc", "certlm.msc",
    "rundll32.exe sysdm.cpl,EditEnvironmentVariables", "control.exe userpasswords2",
    "shell:Downloads", "shell:Startup", "shell:::{ED7BA470-8E54-465E-825C-99712043E01C}",
])
def test_required_surfaces_are_catalogued(target):
    assert any(item["target"] == target for item in settings_catalog.STATIC_SURFACES)


@pytest.mark.parametrize("identifier", [
    "util_regedit", "msc_gpedit", "msc_secpol", "msc_diskmgmt", "msc_services", "msc_compmgmt",
    "util_verifier", "util_msconfig",
])
def test_state_changing_consoles_are_controlled(identifier):
    assert settings_catalog.SURFACES_BY_ID[identifier]["risk"] == "controlled"


def test_opening_ordinary_pages_is_low_risk():
    for identifier in ("bluetooth", "wifi", "cp_network_sharing", "cpl_ncpa", "shell_downloads", "clsid_god_mode"):
        assert settings_catalog.SURFACES_BY_ID[identifier]["risk"] == "low"


def test_edition_specific_entries_carry_an_availability_note():
    for identifier in ("msc_gpedit", "msc_secpol", "msc_virtmgmt", "msc_gpmc", "cp_bitlocker"):
        assert settings_catalog.SURFACES_BY_ID[identifier]["availability"]


@pytest.mark.parametrize("bad", [
    {"kind": "ms_settings", "target": "ms-settings:bluetooth?x=1"},
    {"kind": "msc", "target": "cmd.exe /c whoami", "file": "cmd.exe"},
    {"kind": "cpl", "target": "ncpa.cpl & calc", "file": "ncpa.cpl"},
    {"kind": "utility", "target": "rundll32.exe x", "file": "rundll32.exe", "arguments": "x & calc"},
    {"kind": "utility", "target": r"..\evil.exe", "file": r"..\evil.exe"},
    {"kind": "shell_folder", "target": r"shell:..\..\Windows"},
    {"kind": "shell_clsid", "target": "shell:::{not-a-clsid}"},
    {"kind": "control_name", "target": "Microsoft.X /page a;b", "canonical_name": "Microsoft.X", "page": "a;b"},
    {"kind": "powershell", "target": "Get-Process"},
])
def test_validate_entry_rejects_free_form_targets(bad):
    entry = settings_catalog._entry(id="bad", category="x", title="x", **bad)
    with pytest.raises(ValueError):
        settings_catalog.validate_entry(entry)


# ------------------------------------------------------------------ dynamic ranking

@pytest.mark.parametrize(("query", "acceptable", "top_n"), [
    ("bluetooth", {"bluetooth"}, 1),
    ("blutooth", {"bluetooth"}, 1),
    ("dns", {"network_advanced", "cpl_ncpa"}, 2),
    ("uninstall programs", {"cpl_appwiz", "cp_programs_features", "apps_features"}, 2),
    ("device manager", {"msc_devmgmt", "cp_device_manager", "cpl_hdwwiz"}, 1),
    ("god mode", {"clsid_god_mode"}, 1),
    ("environment variables", {"util_environment_variables"}, 1),
    ("startup apps", {"startup_apps"}, 1),
    ("open wifi settings", {"wifi"}, 1),
    ("show hidden files", {"cp_folder_options"}, 1),
    ("create restore point", {"util_sysprops_protection", "cpl_sysdm_protection"}, 2),
    ("awaaz", {"sound", "volume_mixer"}, 2),
    ("registry editor", {"util_regedit"}, 1),
    ("group policy", {"msc_gpedit"}, 1),
    ("downloads folder", {"shell_downloads"}, 1),
    ("advanced sharing", {"cp_advanced_sharing"}, 1),
])
def test_ranking_finds_expected_surfaces(query, acceptable, top_n):
    ranked = settings_catalog.rank_surfaces(query, settings_catalog.STATIC_SURFACES, limit=10)
    assert ranked, query
    assert acceptable & {item["id"] for item in ranked[:top_n]}, [(i["id"], i["score"]) for i in ranked[:5]]


def test_ranking_returns_descending_scores_and_match_reasons():
    ranked = settings_catalog.rank_surfaces("network", settings_catalog.STATIC_SURFACES, limit=20)
    scores = [item["score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)
    assert len(ranked) > 5
    assert all(item["match"] in {"exact", "phrase", "fuzzy", "token"} for item in ranked)


def test_ranking_rejects_nonsense_and_filters_by_kind():
    assert settings_catalog.rank_surfaces("xqzzv plorbt", settings_catalog.STATIC_SURFACES) == []
    only_msc = settings_catalog.rank_surfaces("manager", settings_catalog.STATIC_SURFACES, kinds=["msc"])
    assert only_msc and all(item["kind"] == "msc" for item in only_msc)


def test_ranking_hides_deprecated_unless_requested():
    hidden = settings_catalog.rank_surfaces("tablet mode", settings_catalog.SETTINGS_CATALOG)
    assert "tablet_mode" not in {item["id"] for item in hidden}
    shown = settings_catalog.rank_surfaces("tablet mode", settings_catalog.SETTINGS_CATALOG, include_deprecated=True)
    assert "tablet_mode" in {item["id"] for item in shown}


def test_search_logic_is_not_a_phrase_table():
    source = open(settings_catalog.__file__, encoding="utf-8").read()
    assert not re.search(r"if\s+query\s*==|elif\s+[\"']", source)


# ------------------------------------------------------------------ Settings compat API

@pytest.mark.parametrize(("query", "expected_id"), [
    ("Bluetooth settings", "bluetooth"),
    ("Wi-Fi settings", "wifi"),
    ("advanced display settings", "display_advanced"),
    ("startup apps", "startup_apps"),
    ("Windows Update history", "update_history"),
    ("microphone privacy", "privacy_microphone"),
    ("volume mixer", "volume_mixer"),
])
def test_settings_search_finds_natural_language_page_names(query, expected_id):
    result = settings_catalog.search_settings_pages(query, limit=10)
    assert expected_id in {item["id"] for item in result["matches"]}
    assert all("score" in item for item in result["matches"])


def test_settings_resolver_accepts_exact_ids_aliases_and_catalogued_uris():
    assert settings_catalog.resolve_settings_page("bluetooth")["id"] == "bluetooth"
    assert settings_catalog.resolve_settings_page("Wi-Fi settings")["id"] == "wifi"
    assert settings_catalog.resolve_settings_page("ms-settings:network-wifi")["id"] == "wifi"
    assert settings_catalog.resolve_settings_page("windows update")["id"] == "windows_update"


def test_settings_resolver_rejects_arbitrary_or_ambiguous_uris():
    with pytest.raises(LookupError):
        settings_catalog.resolve_settings_page("ms-settings:run-any-command")
    with pytest.raises(LookupError, match="ambiguous"):
        settings_catalog.resolve_settings_page("backup")
    with pytest.raises(LookupError):
        settings_catalog.resolve_settings_page("blutooth")  # fuzzy is for search, never for launch


def test_settings_catalogue_pages_are_paginated_without_truncating_total():
    first = settings_catalog.list_settings_pages(limit=50, offset=0)
    second = settings_catalog.list_settings_pages(limit=50, offset=50)
    assert first["count"] == 50
    assert first["next_offset"] == 50
    assert second["offset"] == 50
    assert second["pages"]
    assert first["total_matching"] == second["total_matching"]


def test_settings_catalogue_filters_by_category_and_lifecycle():
    current = settings_catalog.list_settings_pages(category="Update and security", include_deprecated=False, limit=50)
    assert current["pages"]
    assert all(item["category"] == "Update and security" for item in current["pages"])
    assert all(item["lifecycle"] not in {"deprecated", "removed"} for item in current["pages"])
    historical = settings_catalog.search_settings_pages("tablet mode", include_deprecated=True)
    assert any(item["id"] == "tablet_mode" and item["lifecycle"] == "removed" for item in historical["matches"])


# ------------------------------------------------------------------ launchers

def _record_startfile(monkeypatch):
    calls = []
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)
    monkeypatch.setattr(settings, "get_windows_build", lambda: 26300)
    _static(monkeypatch)
    return calls


def test_open_settings_dispatches_only_catalogued_uri(monkeypatch):
    calls = _record_startfile(monkeypatch)
    result = settings.open_settings("Wi-Fi settings")
    assert calls == [(("ms-settings:network-wifi",), {})]
    assert result["target"] == "wifi"
    assert result["verified"] is False
    assert result["source"] == settings.MICROSOFT_SOURCE


def test_open_settings_refuses_removed_and_parameterized_pages(monkeypatch):
    calls = _record_startfile(monkeypatch)
    with pytest.raises(ValueError, match="removed"):
        settings.open_settings("tablet_mode")
    with pytest.raises(ValueError, match="endpoint"):
        settings.open_settings("sound_device_properties")
    assert calls == []


def test_open_settings_enforces_minimum_windows_build(monkeypatch):
    _record_startfile(monkeypatch)
    monkeypatch.setattr(settings, "get_windows_build", lambda: 22000)
    with pytest.raises(OSError, match="requires Windows build 26100"):
        settings.open_settings("hearing_devices")


def test_control_panel_launcher_uses_only_fixed_arguments(monkeypatch):
    calls = _record_startfile(monkeypatch)
    result = settings.open_control_panel("network_sharing_center")
    (args, kwargs), = calls
    assert os.path.basename(args[0]).lower() == "control.exe" and os.path.isabs(args[0])
    assert kwargs == {"arguments": "/name Microsoft.NetworkAndSharingCenter"}
    assert result["verified"] is False
    with pytest.raises(ValueError, match="allowlist"):
        settings.open_control_panel("powershell -command whoami")
    assert len(calls) == 1


def test_legacy_console_keys_still_resolve(monkeypatch):
    calls = _record_startfile(monkeypatch)
    result = settings.open_console("device_manager")
    (args, kwargs), = calls
    assert os.path.basename(args[0]).lower() == "devmgmt.msc" and os.path.isabs(args[0])
    assert kwargs == {}
    assert result["target"] == "msc_devmgmt"
    with pytest.raises(ValueError, match="allowlist"):
        settings.open_console("cmd.exe")
    assert len(calls) == 1
