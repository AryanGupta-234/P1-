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
    assert "without enough evidence" in result["explanation"].lower()
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
    (node_modules / ".hidden-cache" / "cache.artifact").write_bytes(b"h" * 17)
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


def test_python_environment_report_breaks_out_individual_site_packages(tmp_path):
    site_packages = tmp_path / ".venv" / "Lib" / "site-packages"
    (site_packages / "requests").mkdir(parents=True)
    (site_packages / "numpy").mkdir()
    (site_packages / "requests" / "metadata.py").write_bytes(b"r" * 47)
    (site_packages / "numpy" / "core.pyd").write_bytes(b"n" * 89)

    report = storage_intelligence._measure(
        str(tmp_path / ".venv"), max_entries=100,
        deadline=time.monotonic() + 5, category="python-environments",
    )
    packages = {item["name"]: item["bytes"] for item in report["top_level"]}
    assert packages["requests"] == 47
    assert packages["numpy"] == 89


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
    assert "4.0 GiB" in reason


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



def test_shared_runtime_admission_yields_to_healthy_idle_work(monkeypatch):
    monkeypatch.setattr(runtime_engine, "snapshot", lambda: {
        "mode": "balanced",
        "game_active": False,
        "available_memory_gib": 8.0,
        "cpu_percent": 0.0,
    })
    allowed, reason = runtime_engine.admit_optional_work(
        "test job", min_available_gib=4.0, max_cpu_percent=45.0,
    )
    assert allowed is True
    assert "admitted" in reason


def test_shared_runtime_admission_defers_optional_work_under_cpu_pressure(monkeypatch):
    monkeypatch.setattr(runtime_engine, "snapshot", lambda: {
        "mode": "balanced",
        "game_active": False,
        "available_memory_gib": 8.0,
        "cpu_percent": 75.0,
    })
    allowed, reason = runtime_engine.admit_optional_work(
        "test job", min_available_gib=4.0, max_cpu_percent=45.0,
    )
    assert allowed is False
    assert "CPU at 75%" in reason



def test_pending_desktop_alerts_are_delivered_by_the_agent_when_idle(monkeypatch):
    delivered = []
    monkeypatch.setattr(agent_assist, "settings", lambda: {
        **agent_assist.DEFAULTS, "enabled": True, "agent_notifications": True,
        "max_notifications_per_hour": 4,
    })
    monkeypatch.setattr(agent_assist, "_runtime_suppressed", lambda _settings: False)

    def fake_db(sql, params=()):
        if "SELECT COUNT(*) FROM agent_notifications WHERE delivered_at" in sql:
            return [(0,)]
        if "SELECT id,title,question,suggested_fix FROM agent_notifications" in sql:
            return [(77, "Device failed", "Which device?", "Check the signed driver.")]
        return []

    monkeypatch.setattr(agent_assist.core, "db", fake_db)
    monkeypatch.setattr(
        agent_assist, "_agent_toast",
        lambda title, body: delivered.append((title, body)) or True,
    )

    assert agent_assist._deliver_pending_notifications() == 1
    assert delivered == [("Device failed", "Which device? Next check: Check the signed driver.")]


def test_pending_desktop_alerts_stay_queued_during_game_or_resource_pressure(monkeypatch):
    monkeypatch.setattr(agent_assist, "settings", lambda: {
        **agent_assist.DEFAULTS, "enabled": True, "agent_notifications": True,
    })
    monkeypatch.setattr(agent_assist, "_runtime_suppressed", lambda _settings: True)
    monkeypatch.setattr(agent_assist.core, "db", lambda *_args, **_kwargs: pytest.fail("queue must not be consumed"))
    monkeypatch.setattr(agent_assist, "_agent_toast", lambda *_args: pytest.fail("toast must be deferred"))

    assert agent_assist._deliver_pending_notifications() == 0


def test_agent_assistant_classifies_common_windows_faults():
    cases = [
        ("Kernel-Power 41 after unexpected reboot", "blue-screen"),
        ("WindowsUpdateClient installation failed with 0x8024", "windows-update"),
        ("Startup Repair failed to load bootmgr", "boot-startup"),
        ("Windows Audio service audiosrv failed", "audio"),
        ("Unknown USB device descriptor request failed", "peripheral"),
        ("Application Hang: app.exe is not responding", "application-hang"),
        ("Battery power state transition failed", "power-battery"),
    ]
    for message, category in cases:
        assert agent_assist._classify("Windows Event Log", message, "warn")["category"] == category


def test_structured_event_evidence_enriches_classification_without_secrets():
    evidence = agent_assist._event_data_evidence(
        '{"problem":"CM_PROB_FAILED_START","device":"Realtek Wi-Fi","code":10,"api_key":"do-not-store"}'
    )
    assert evidence["problem"] == "CM_PROB_FAILED_START"
    assert evidence["device"] == "Realtek Wi-Fi"
    assert "api_key" not in evidence
    context = " ".join(f"{key}: {value}" for key, value in evidence.items())
    assert agent_assist._classify("device-event", context, "warn")["category"] == "driver"


def test_storage_review_findings_get_a_review_only_assistant_prompt():
    result = agent_assist._classify(
        "storage-intelligence",
        "Storage review candidate: old archive uses 900 MB",
        "warn",
    )
    assert result["category"] == "storage-review"
    assert "will not delete" in result["fix"]


def test_ai_diagnosis_quota_counts_unavailable_jobs_too(monkeypatch):
    monkeypatch.setattr(
        agent_assist.core, "db",
        lambda *_args, **_kwargs: [(2,)],
    )
    assert agent_assist._ai_diagnosis_budget_available(now=10000) is False
    monkeypatch.setattr(
        agent_assist.core, "db",
        lambda *_args, **_kwargs: [(1,)],
    )
    assert agent_assist._ai_diagnosis_budget_available(now=10000) is True


def test_storage_measurement_exposes_largest_files_and_extension_counts(tmp_path):
    (tmp_path / "small.json").write_bytes(b"j" * 11)
    (tmp_path / "large.bin").write_bytes(b"b" * 100)
    report = storage_intelligence._measure(
        str(tmp_path), max_entries=100, deadline=time.monotonic() + 5,
    )
    assert report["top_files"][0]["name"] == "large.bin"
    assert report["extension_counts"][".bin"] == 1
    assert report["extension_counts"][".json"] == 1


def test_storage_measurement_yields_when_foreground_priority_changes(tmp_path):
    for index in range(100):
        (tmp_path / f"item-{index:03}.dat").write_bytes(b"x")
    report = storage_intelligence._measure(
        str(tmp_path), max_entries=1000, deadline=time.monotonic() + 5,
        should_yield=lambda: True,
    )
    assert report["yielded"] is True
    assert report["partial"] is True
    assert report["entries_visited"] == 64


def test_runtime_fails_closed_when_cpu_telemetry_is_unknown(monkeypatch):
    monkeypatch.setattr(runtime_engine.core, "LIVE", {"cpu": None})
    monkeypatch.setattr(runtime_engine.core, "STATE", {})
    monkeypatch.setattr(runtime_engine.safeguard, "snapshot", lambda: {
        "valorant_active": False,
        "process_detection_complete": True,
        "kernel_trace_allowed": False,
    })
    state = runtime_engine.evaluate()
    assert state["mode"] == "telemetry_degraded"
    assert state["telemetry_ready"] is False
    assert state["cpu_percent"] is None
    allowed, reason = runtime_engine.admit_optional_work("unknown telemetry")
    assert allowed is False
    assert "telemetry_degraded" in reason



def test_agent_assistant_covers_whea_and_defender_without_unsafe_remediation():
    whea = agent_assist._classify("WHEA-Logger", "WHEA_UNCORRECTABLE_ERROR", "critical")
    assert whea["category"] == "hardware-error"
    assert "voltage" in whea["fix"].lower()

    defender = agent_assist._classify(
        "Microsoft Defender", "Windows Defender threat detected", "high",
    )
    assert defender["category"] == "windows-security"
    assert "disable Defender" in defender["fix"]


def test_storage_intelligence_excludes_known_game_library_roots():
    protected = {"steam", "steamapps", "steamlibrary", "epic games", "riot games", "valorant"}
    assert protected <= storage_intelligence.GAME_ROOT_NAMES
    assert protected <= storage_intelligence.SKIP_NAMES


def test_runtime_keeps_valorant_guard_when_cpu_sample_is_missing(monkeypatch):
    monkeypatch.setattr(runtime_engine.core, "LIVE", {"cpu": None})
    monkeypatch.setattr(runtime_engine.core, "STATE", {"game": {"name": "VALORANT"}})
    monkeypatch.setattr(runtime_engine.safeguard, "snapshot", lambda: {
        "valorant_active": True,
        "process_detection_complete": True,
        "kernel_trace_allowed": False,
    })
    state = runtime_engine.evaluate()
    assert state["mode"] == "valorant_guarded"
    assert state["game_active"] is True
    assert state["telemetry_ready"] is False
    allowed, reason = runtime_engine.admit_optional_work("foreground priority")
    assert allowed is False
    assert "valorant_guarded" in reason



def test_agent_native_toast_contains_question_and_safe_next_check():
    body = agent_assist._toast_body(
        "Which device is affected?",
        "Verify the signed driver and exact Device Manager problem code.",
    )
    assert "Which device is affected?" in body
    assert "Next check:" in body
    assert "signed driver" in body
    assert len(body) <= 240



def test_ai_diagnosis_quota_caps_pending_backlog_even_after_hour_rollover(monkeypatch):
    def fake_db(sql, params=()):
        if "created_at>=?" in sql:
            return [(0,)]
        if "status IN ('queued','running')" in sql:
            return [(2,)]
        raise AssertionError(sql)
    monkeypatch.setattr(agent_assist.core, "db", fake_db)
    assert agent_assist._ai_diagnosis_budget_available(now=20000) is False
