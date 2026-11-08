import pytest

from apex.windows import settings, settings_catalog


def test_catalogue_contains_a_broad_documented_settings_inventory():
    identifiers = [item["id"] for item in settings_catalog.SETTINGS_CATALOG]
    assert len(identifiers) >= 180
    assert len(identifiers) == len(set(identifiers))
    assert all(item["uri"].startswith("ms-settings:") for item in settings_catalog.SETTINGS_CATALOG)
    assert {
        "Accounts",
        "Apps",
        "Devices",
        "Accessibility",
        "Gaming",
        "Network and internet",
        "Personalization",
        "Privacy",
        "Sound",
        "System",
        "Time and language",
        "Update and security",
    }.issubset({item["category"] for item in settings_catalog.SETTINGS_CATALOG})


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("Bluetooth settings", "bluetooth"),
        ("Wi-Fi settings", "wifi"),
        ("advanced display settings", "display_advanced"),
        ("startup apps", "startup_apps"),
        ("Windows Update history", "update_history"),
        ("microphone privacy", "privacy_microphone"),
        ("volume mixer", "volume_mixer"),
    ],
)
def test_settings_search_finds_natural_language_page_names(query, expected_id):
    result = settings_catalog.search_settings_pages(query, limit=10)
    ids = {item["id"] for item in result["matches"]}
    assert expected_id in ids


def test_settings_resolver_accepts_exact_ids_aliases_and_documented_uris():
    assert settings_catalog.resolve_settings_page("bluetooth")["id"] == "bluetooth"
    assert settings_catalog.resolve_settings_page("Wi-Fi settings")["id"] == "wifi"
    assert settings_catalog.resolve_settings_page("ms-settings:network-wifi")["id"] == "wifi"
    assert settings_catalog.resolve_settings_page("windows update")["id"] == "windows_update"


def test_settings_resolver_rejects_arbitrary_or_ambiguous_uris():
    with pytest.raises(LookupError):
        settings_catalog.resolve_settings_page("ms-settings:run-any-command")
    with pytest.raises(LookupError, match="ambiguous"):
        settings_catalog.resolve_settings_page("backup")


def test_settings_catalogue_pages_are_paginated_without_truncating_total():
    first = settings_catalog.list_settings_pages(limit=50, offset=0)
    second = settings_catalog.list_settings_pages(limit=50, offset=50)

    assert first["count"] == 50
    assert first["next_offset"] == 50
    assert second["offset"] == 50
    assert second["pages"]
    assert first["total_matching"] == second["total_matching"]


def test_settings_catalogue_filters_by_category_and_lifecycle():
    current = settings_catalog.list_settings_pages(
        category="Update and security",
        include_deprecated=False,
        limit=50,
    )
    assert current["pages"]
    assert all(item["category"] == "Update and security" for item in current["pages"])
    assert all(item["lifecycle"] not in {"deprecated", "removed"} for item in current["pages"])

    historical = settings_catalog.search_settings_pages(
        "tablet mode", include_deprecated=True,
    )
    assert any(item["id"] == "tablet_mode" and item["lifecycle"] == "removed"
               for item in historical["matches"])


def test_open_settings_dispatches_only_catalogued_uri(monkeypatch):
    calls = []
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda uri, **kwargs: calls.append((uri, kwargs)), raising=False)
    monkeypatch.setattr(settings, "get_windows_build", lambda: 26300)

    result = settings.open_settings("Wi-Fi settings")

    assert calls == [("ms-settings:network-wifi", {})]
    assert result["target"] == "wifi"
    assert result["verified"] is False
    assert result["source"] == settings.MICROSOFT_SOURCE if hasattr(settings, "MICROSOFT_SOURCE") else "Microsoft Learn"


def test_open_settings_refuses_removed_and_parameterized_pages(monkeypatch):
    calls = []
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda *args, **kwargs: calls.append(args), raising=False)
    monkeypatch.setattr(settings, "get_windows_build", lambda: 26300)

    with pytest.raises(ValueError, match="removed"):
        settings.open_settings("tablet_mode")
    with pytest.raises(ValueError, match="endpoint"):
        settings.open_settings("sound_device_properties")
    assert calls == []


def test_open_settings_enforces_documented_minimum_windows_build(monkeypatch):
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(settings, "get_windows_build", lambda: 22000)

    with pytest.raises(OSError, match="requires Windows build 26100"):
        settings.open_settings("hearing_devices")


def test_control_panel_launcher_uses_only_fixed_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)

    result = settings.open_control_panel("network_sharing_center")

    assert calls == [(("control.exe",), {"arguments": "/name Microsoft.NetworkAndSharingCenter"})]
    assert result["verified"] is False
    with pytest.raises(ValueError, match="allowlist"):
        settings.open_control_panel("powershell -command whoami")


def test_legacy_mmc_console_targets_are_allowlisted(monkeypatch):
    calls = []
    monkeypatch.setattr(settings.os, "name", "nt")
    monkeypatch.setattr(settings.os, "startfile", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)

    result = settings.open_console("device_manager")

    assert calls == [(("devmgmt.msc",), {})]
    assert result["verified"] is False
    with pytest.raises(ValueError, match="allowlist"):
        settings.open_console("cmd.exe")
