from __future__ import annotations

import time

import pytest

from sentinel import agent_assist, runtime_engine, storage_intelligence


def test_agent_assistant_classifies_driver_start_failure():
    result = agent_assist._classify(
        "windows-eventlog",
        "Realtek 8821CE device cannot start. CM_PROB_FAILED_START Code 10",
        "error",
    )
    assert result["category"] == "driver"
    assert "Device Manager" in result["fix"]
    assert result["question"]


def test_agent_assistant_classifies_network_layers_without_mutating_them():
    result = agent_assist._classify("network", "DNS lookup failed on Wi-Fi", "warn")
    assert result["category"] == "network"
    assert "DNS resolution" in result["fix"]
    assert "unchanged" in result["fix"]


def test_agent_assistant_generic_finding_is_explicit_about_uncertainty():
    result = agent_assist._classify("unknown", "Unusual warning occurred", "warn")
    assert result["category"] == "system"
    assert "not enough evidence" in result["explanation"].lower()
    assert "until the symptom is narrowed down" in result["fix"]


def test_agent_assistant_rejects_unknown_setting():
    with pytest.raises(ValueError, match="unknown agent-assist setting"):
        agent_assist.update_settings({"execute_repairs_automatically": True})


def test_agent_assistant_rejects_unbounded_notification_rate():
    with pytest.raises(ValueError, match="1 to 12"):
        agent_assist.update_settings({"max_notifications_per_hour": 100})


def test_storage_measurement_reports_package_sizes_extensions_and_hidden_files(tmp_path):
    node_modules = tmp_path / "node_modules"
    (node_modules / "react").mkdir(parents=True)
    (node_modules / "@scope" / "library").mkdir(parents=True)
    (node_modules / ".hidden-cache").mkdir(parents=True)

    (node_modules / "react" / "index.js").write_bytes(b"r" * 101)
    (node_modules / "@scope" / "library" / "index.js").write_bytes(b"s" * 203)
    (node_modules / ".hidden-cache" / ".artifact").write_bytes(b"h" * 17)
    (node_modules / ".hidden-cache" / "ordinary.dat").write_bytes(b"o" * 11)

    report = storage_intelligence._measure(
        str(node_modules), max_entries=100,
        deadline=time.monotonic() + 5,
    )
    packages = {item["name"]: item["bytes"] for item in report["top_level"]}

    assert report["bytes"] == 332
    assert packages["react"] == 101
    assert packages["@scope/library"] == 203
    assert report["hidden_files"] == 2
    assert report["hidden_bytes"] == 28
    assert report["extensions"][".js"] == 304
    assert report["extensions"][".artifact"] == 17
    assert report["extensions"][".dat"] == 11


def test_storage_scan_is_bounded_and_marks_budget_exhaustion(tmp_path):
    root = tmp_path / "large"
    root.mkdir()
    for index in range(30):
        (root / f"file-{index}.bin").write_bytes(b"x" * 4)

    report = storage_intelligence._measure(
        str(root), max_entries=5,
        deadline=time.monotonic() + 5,
    )
    assert report["entries_visited"] == 5
    assert report["partial"] is True


def test_storage_scheduler_defers_during_active_game(monkeypatch):
    monkeypatch.setattr(runtime_engine, "snapshot", lambda: {
        "mode": "game_optimized",
        "game_active": True,
        "available_memory_gib": 12,
    })
    allowed, reason = storage_intelligence._resources_allow_scan()
    assert allowed is False
    assert "game_optimized" in reason


def test_storage_scheduler_defers_when_memory_headroom_is_low(monkeypatch):
    monkeypatch.setattr(runtime_engine, "snapshot", lambda: {
        "mode": "balanced",
        "game_active": False,
        "available_memory_gib": 2.5,
    })
    allowed, reason = storage_intelligence._resources_allow_scan()
    assert allowed is False
    assert "4 GiB" in reason


def test_storage_settings_reject_full_volume_unbounded_scan():
    with pytest.raises(ValueError, match="max_entries"):
        storage_intelligence.update_settings({"max_entries": 1_000_000})


def test_storage_metadata_only_module_has_no_delete_or_uninstall_surface():
    source = __import__("pathlib").Path(storage_intelligence.__file__).read_text(encoding="utf-8")
    assert "file_contents_opened" in source
    assert "files_deleted" in source
    assert "packages_uninstalled" in source
    assert "os.remove(" not in source
    assert "shutil.rmtree(" not in source



@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("Driver latency: DPC time 16% avg / 40% peak", "driver-latency"),
        ("Real memory pressure: 600 MB free, pagefile", "memory"),
        ("CPU spike caused by app.exe", "cpu"),
        ("Disk latency spike: 80 ms", "disk-performance"),
        ("GPU throttling detected", "thermal"),
        ("process-review score requires attention", "process-review"),
    ],
)
def test_agent_assistant_covers_common_system_fault_classes(message, category):
    result = agent_assist._classify("diagnostic", message, "error")
    assert result["category"] == category
    assert result["title"]
    assert result["question"]
    assert result["fix"]
