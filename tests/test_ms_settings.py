from pathlib import Path
import json

import pytest

from aie.ms_settings import (
    SettingsEntry, load_catalog, merge_catalog, save_catalog, search_catalog,
    starter_catalog, validate_entry,
)


def test_starter_catalog_is_unverified_and_searchable():
    entries = starter_catalog()
    assert len(entries) >= 40
    assert all(item.validation_status == "unverified" for item in entries)
    assert search_catalog(entries, "privacy microphone")[0].uri == "ms-settings:privacy-microphone"


def test_import_json_and_deduplicate_case_insensitively(tmp_path: Path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"items": [
        {"uri": "ms-settings:display", "title": "Display"},
        {"uri": "MS-SETTINGS:DISPLAY", "title": "Screen"},
    ]}), encoding="utf-8")
    entries = load_catalog(path)
    assert len(entries) == 1
    assert entries[0].title == "Screen"


def test_import_csv(tmp_path: Path):
    path = tmp_path / "catalog.csv"
    path.write_text("uri,title,category\nms-settings:display,Display,System\n", encoding="utf-8")
    assert load_catalog(path)[0].category == "System"


@pytest.mark.parametrize("uri", [
    "https://example.com", "ms-settings:", "ms-settings:../evil",
    "ms-settings:display\ncalc.exe", "ms-settings://example.com",
])
def test_reject_invalid_uri(uri: str):
    with pytest.raises(ValueError):
        validate_entry({"uri": uri, "title": "Bad"})


def test_build_range_and_status_validation():
    with pytest.raises(ValueError):
        validate_entry({"uri": "ms-settings:display", "title": "Display",
                        "min_build": 30000, "max_build": 20000})
    with pytest.raises(ValueError):
        validate_entry({"uri": "ms-settings:display", "title": "Display",
                        "validation_status": "supported"})


def test_search_requires_all_terms_and_bounds():
    entries = starter_catalog()
    assert search_catalog(entries, "privacy webcam")
    assert not search_catalog(entries, "privacy nonexistent")
    with pytest.raises(ValueError):
        search_catalog(entries, "x", 0)


def test_save_and_merge_roundtrip(tmp_path: Path):
    path = tmp_path / "nested" / "catalog.json"
    merged = merge_catalog(starter_catalog(), [
        SettingsEntry("ms-settings:custom", "Custom", source="import")
    ])
    save_catalog(path, merged)
    assert len(load_catalog(path)) == len(merged)



def test_bundled_documented_catalogue_has_provenance_and_200_plus_entries():
    from aie.ms_settings import documented_catalog

    entries = documented_catalog()
    assert len(entries) >= 200
    assert all(item.validation_status == "documented" for item in entries)
    assert all(item.source_url.startswith("https://learn.microsoft.com/") for item in entries)
    assert any("Deprecated" in item.version_notes for item in entries)


def test_bundled_catalogue_retains_requirements_metadata():
    from aie.ms_settings import documented_catalog

    entries = documented_catalog()
    camera = next(item for item in entries if item.uri == "ms-settings:camera")
    assert "Windows 11" in camera.version_notes
    assert documented_catalog()
