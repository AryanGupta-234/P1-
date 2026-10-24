from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = (ROOT / "sentinel" / "maintenance.py").read_text(encoding="utf-8")
SAFEGUARD = (ROOT / "sentinel" / "safeguard.py").read_text(encoding="utf-8")
SERVER = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
MAINTENANCE = (ROOT / "sentinel" / "maintenance.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "install.bat").read_text(encoding="utf-8")


def test_maintenance_kill_switch_defaults_on_and_mutations_are_previewed():
    assert "kill_switch INTEGER NOT NULL DEFAULT 1" in MAINTENANCE
    assert "def preview_action(" in MAINTENANCE and "def execute_preview(" in MAINTENANCE
    assert "confirmed is not True" in MAINTENANCE
    assert "_PREVIEW_LOCK" in MAINTENANCE
    assert '"automatic_allowed": False' in MAINTENANCE


def test_vanguard_guard_covers_every_maintenance_mutation():
    for action in (
        "maint_startup_disable", "maint_cleanup", "maint_dns_set", "maint_adapter_restart",
        "maint_winsock_reset", "maint_driver_install", "maint_driver_rollback",
        "maint_windows_repair", "maint_service_restart", "maint_power_mode",
        "maint_trim_volume", "maint_process_tune",
    ):
        assert action in SAFEGUARD
    assert "valorant_read_only" in SAFEGUARD
    assert "process_state_unknown" in SAFEGUARD


def test_scheduler_is_diagnostic_only():
    start = MAINTENANCE.index("def _scheduler_loop()")
    end = MAINTENANCE.index("def start()", start)
    scheduler = MAINTENANCE[start:end]
    assert "_read_only_diagnostics()" in scheduler
    assert "execute_preview(" not in scheduler and "_apply_action(" not in scheduler
    assert 'if not policy["scheduler_enabled"] or not IS_WIN' in scheduler


def test_dns_test_is_read_only_and_dns_setter_is_valid():
    lines = [line for line in MAINTENANCE.splitlines() if "Set-DnsClientServerAddress" in line]
    assert lines and all("-AddressFamily" not in line for line in lines)
    assert "def test_dns_servers(" in MAINTENANCE and "Resolve-DnsName" in MAINTENANCE
    assert "/api/maintenance/dns-test" in SERVER


def test_resource_pressure_defers_driver_inventory_and_thermal_is_predictive():
    assert "Deferred during game session or resource pressure." in MAINTENANCE
    assert "available_gib >= 3.0" in MAINTENANCE and "cpu_percent < 85.0" in MAINTENANCE
    assert "minutes_to_threshold" in MAINTENANCE
    assert "now - float(latest[0][0]) >= 900" in MAINTENANCE


def test_status_refresh_runs_off_the_request_thread():
    assert "def queue_diagnostics(" in MAINTENANCE
    assert "threading.Thread(target=_refresh_diagnostics_worker" in MAINTENANCE


def test_revert_all_skips_operations_without_safe_undo():
    assert "def revert_all(" in MAINTENANCE
    assert "no safe automatic undo" in MAINTENANCE
    assert "/api/maintenance/revert-all" in SERVER


def test_installer_checks_new_engines():
    assert "sentinel\\maintenance.py" in INSTALLER
    assert "sentinel\\approval_engine.py" in INSTALLER


def test_driver_install_journal_has_a_real_guarded_undo_path():
    undo_start = MAINTENANCE.index("def undo(")
    undo_end = MAINTENANCE.index("def journal(", undo_start)
    undo_source = MAINTENANCE[undo_start:undo_end]
    assert 'detail.get("kind") == "driver_restore"' in undo_source
    assert "_run_restore_point(\"driver rollback\")" in undo_source
    assert '["pnputil.exe", "/add-driver", backup_inf, "/install"]' in undo_source


def test_driver_candidate_requires_device_id_or_instance_prefix_match():
    assert 'normalized_device == str(value).strip().casefold()' in MAINTENANCE
    assert 'normalized_device.startswith(str(value).strip().casefold() + "\\\\")' in MAINTENANCE
    assert "hardware.includes(id)" not in (ROOT / "ui" / "app.js").read_text(encoding="utf-8")


def test_system_evidence_report_uses_local_rolling_metrics_and_preserves_safety():
    assert "def _system_health_report(" in MAINTENANCE
    assert "core.HIST.get(key, [])" in MAINTENANCE
    assert '"cpu_pressure"' in MAINTENANCE and '"memory_pressure"' in MAINTENANCE
    assert '"thermal_pressure"' in MAINTENANCE and '"disk_capacity"' in MAINTENANCE
    assert '"network_latency"' in MAINTENANCE and '"gpu_throttle"' in MAINTENANCE
    assert "automatic_execution\": False" in MAINTENANCE


def test_oem_utility_detection_is_registry_read_only_and_guided_only():
    assert "def _oem_control_inventory(" in MAINTENANCE
    assert "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in MAINTENANCE
    assert '"control_mode": "guided_only"' in MAINTENANCE
    assert '"firmware_writes_enabled": False' in MAINTENANCE


def test_game_library_relocation_is_manifest_based_and_never_moves_files():
    assert "def _game_library_inventory(" in MAINTENANCE
    assert "appmanifest_*.acf" in MAINTENANCE
    assert "*.item" in MAINTENANCE
    assert "def game_relocation_plan(" in MAINTENANCE
    assert '"files_will_be_moved_by_sentinel": False' in MAINTENANCE
    assert "/api/maintenance/game-relocation/plan" in SERVER


def test_thermal_forecast_uses_bounded_samples_and_is_alert_only():
    assert "minutes_to_threshold" in MAINTENANCE
    assert 'key = "thermal:" + name' in MAINTENANCE
    assert "Trend-based alert only; no automatic fan, power, or process action." in MAINTENANCE


def test_epic_empty_install_location_is_not_treated_as_current_directory():
    assert 'raw_install_path = str(item.get("InstallLocation") or "").strip()' in MAINTENANCE
    assert "if not app_name or not title or not raw_install_path:" in MAINTENANCE


def test_game_relocation_plan_never_moves_launcher_owned_files():
    start = MAINTENANCE.index("def game_relocation_plan(")
    end = MAINTENANCE.index("def _average_metric(", start)
    source = MAINTENANCE[start:end]
    assert '"files_will_be_moved_by_sentinel": False' in source
    assert "shutil.move" not in source
    assert "os.rename(" not in source
    assert "/api/maintenance/game-relocation/plan" in SERVER
