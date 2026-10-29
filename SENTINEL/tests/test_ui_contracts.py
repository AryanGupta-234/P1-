from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_multiple_dom_nodes_use_collection_selector_before_for_each():
    source = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    invalid = [
        (line_number, line.strip())
        for line_number, line in enumerate(source.splitlines(), 1)
        if re.search(r'(?<!\$)\$\s*\([^)]*\)\s*\.forEach', line)
    ]
    assert not invalid, "Single-element querySelector() used with forEach(): " + repr(invalid)


def test_intelligence_evidence_binding_uses_collection_selector():
    source = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert "$$('[data-state-evidence]').forEach" in source
    assert "function ixList(" in source


def test_managed_sensor_provider_ui_and_boot_contract_are_present():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
    assert 'id="adv-provider-install"' in html
    assert 'id="adv-sensor-inventory"' in html
    assert 'api("/api/hardware/provider/start"' in app
    for element_id in (
        "bootProgress", "bootPct", "bootStage", "bootDetail", "bootLog",
        "bootModules", "bootCpuValue", "bootRamValue", "bootGpuValue", "bootDpcValue",
    ):
        assert f'id="{element_id}"' in html
    assert 'id="bootRetry"' in html
    assert "function showBootRetry(" in app
    assert 'retry.onclick = () => location.reload()' in app
    assert "endBoot();" not in app[app.index('boot().catch(error =>'):]
    assert "bootSkip" not in html + app + css
    assert "SKIP INTRO" not in html + app + css
    assert "API_CONCURRENCY = 4" in app
    assert "API_TIMEOUT_MS = 16000" in app
    assert "await runPool(jobs)" in app
    assert "await runPool(secondaryJobs)" in app
    assert "void runBatch" not in app
    assert "const minimumDisplayMs = 900" in app
    assert "Promise.allSettled([" in app
    assert 'apiRetry("/api/snapshot", 2)' in app
    assert "data-boot-module" in app
    assert 'id="cmd-performance-chart"' in html
    assert '$$("[data-command-route]")' in app
    assert 'id="proc-live-total"' in html
    assert 'id="proc-live-visible"' in html
    assert 'id="proc-live-services"' in html
    assert 'id="proc-live-review"' in html
    assert 'id="proc-load-bars"' in html
    assert "proc-load-bars" in app
    assert ".proc-command-strip" in css and ".proc-load-item" in css
    assert ".guided-detail" in css
    assert 'class="command-more-metrics"' in html
    assert "function renderCommandVisuals()" in app
    assert 'id="net-signal-strip"' in html
    assert 'id="kernel-signal-strip"' in html
    assert 'id="sys-host-name"' in html
    assert "function renderNetworkSignals()" in app
    assert "function renderKernelSignals()" in app
    assert "function updateSignalTile(" in app
    assert 'document.getElementById("sys-secureboot-value")' in app
    assert 'style.setProperty("--signal-level"' in app
    assert ".signal-page-head" in css and ".signal-strip" in css
    assert ".system-node-banner" in css
    assert "<details class=" in html
    assert "ixLoaded = true" in app and "if (ixBusy) return ixLoaded" in app
    assert 'id="ag-source-map"' in html
    assert 'id="ag-map-summary"' in html
    assert 'data-engine-pulse="safeguard"' in html
    assert 'data-engine-pulse="runtime"' in html
    assert 'data-engine-pulse="ai"' in html
    assert 'data-engine-pulse="memory"' in html
    assert 'data-engine-pulse="wpr"' in html
    assert "function renderAgentHealthMap(matrix)" in app
    assert "function setEnginePulse(" in app
    assert "renderAgentHealthMap(matrix)" in app
    assert ".agent-health-map" in css and ".agent-source-card" in css
    assert ".engine-pulse-rail" in css and ".engine-pulse-card" in css
    assert "DETAILED WORKER / HEARTBEAT TELEMETRY" in html
    assert ".boot-console" in css and ".boot-module.loading" in css
    assert ".boot-live-readouts" in css
    assert "overflow-wrap:anywhere" in css
    assert "workspacePanelEnter" in css and "commandHeroScan" in css
    assert "boot().catch(error =>" in app
    assert "provider.next_step" in app

def test_activity_workspace_and_learned_launch_are_connected():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert 'data-v="activityx"' in html
    assert 'id="v-activityx"' in html
    assert 'id="ax-auto-launch"' in html
    assert 'id="ax-hour-chart"' in html
    assert 'api("/api/activity/launch"' in app
    assert "function renderActivityIntelligence(" in app


def test_dashboard_uses_wpr_as_capture_requirement_and_xperf_as_optional():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert "wpr.exe" in app
    assert "Xperf is optional" in app
    assert 'id="engine-wpr" disabled' in html
    assert "dedicated per-action UAC trace broker is not yet implemented" in html
    assert 'id="adv-etw-interval"' in html
    assert "etw_auto_interval_s" in app


def test_maintenance_workspace_is_in_full_boot_queue_and_preview_gated():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert 'data-v="maint"' in html and 'id="v-maint"' in html
    for element_id in (
        "maint-kill-switch", "maint-scheduler", "maint-cleanup-run", "maint-startup-run",
        "maint-dns-test", "maint-adapter-run", "maint-winsock-run", "maint-driver-run",
        "maint-driver-rollback-run", "maint-repair-run", "maint-service-run",
        "maint-power-run", "maint-trim-run", "maint-process-run", "maint-revert-all",
    ):
        assert f'id="{element_id}"' in html
    assert '["maint", "MAINTENANCE"' in app
    assert 'await loadMaintenance(false)' in app
    assert "function maintenancePreview(" in app
    assert 'api("/api/maintenance/execute"' in app
    assert "initMaintenance(); initAgentAutomation(); initLocalAutomation(); initComponentIntelligence(); initWindowsKnowledge(); initVoice();" in app
    assert "await runPool(jobs)" in app and "await runPool(secondaryJobs)" in app


def test_original_detailed_boot_console_remains_available():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    for element_id in ("bootModules", "bootLog", "bootProgress", "bootDetail", "bootGauge",
                       "bootCpuValue", "bootRamValue", "bootGpuValue", "bootDpcValue"):
        assert f'id="{element_id}"' in html


def test_maintenance_health_report_and_game_planner_are_visible():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert 'id="maint-health-report"' in html
    assert 'id="maint-game-choice"' in html
    assert 'id="maint-game-target"' in html
    assert 'id="maint-game-plan"' in html
    assert "function renderMaintenanceIntelligence()" in app
    assert 'api("/api/maintenance/game-relocation/plan"' in app
    assert "health.coverage_count" in app


def test_windows_knowledge_workspace_and_admin_broker_are_connected():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    for element_id in (
        "ix-kb-url", "ix-kb-title", "ix-kb-licence", "ix-kb-edition",
        "ix-kb-architecture", "ix-kb-api-version", "ix-kb-component",
        "ix-kb-min-build", "ix-kb-max-build", "ix-kb-add", "ix-kb-query",
        "ix-kb-search", "ix-kb-sources",
        "ix-kb-results", "ix-kb-state", "maint-admin-note",
    ):
        assert f'id="{element_id}"' in html
    assert "function initWindowsKnowledge()" in app
    assert 'api("/api/knowledge/source/register"' in app
    assert 'api("/api/knowledge/source/ingest"' in app
    assert 'api("/api/knowledge/search?' in app
    assert "/api/maintenance/privilege" in app
    assert "/api/knowledge/status" in server and "/api/knowledge/search" in server
    assert "/api/knowledge/sources" in server
    assert "/api/knowledge/source/ingest" in server


def test_windows_specialist_is_local_rag_advisory_and_visible():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    specialist = (ROOT / "sentinel" / "windows_intelligence.py").read_text(encoding="utf-8")
    assert 'id="ix-win-question"' in html and 'id="ix-win-diagnose"' in html
    assert 'id="ix-win-result"' in html
    assert 'api("/api/windows-intelligence/diagnose"' in app
    assert '"/api/windows-intelligence/diagnose"' in server
    assert "automatic_execution" in specialist
    assert "ALLOWED_ACTION_IDS" in specialist
    assert "ai.CLOUD" in specialist
    assert "STORE.search(question, limit=6)" in specialist



def test_proactive_assistant_and_storage_controls_are_agent_backed():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    assistant = (ROOT / "sentinel" / "agent_assist.py").read_text(encoding="utf-8")
    storage = (ROOT / "sentinel" / "storage_intelligence.py").read_text(encoding="utf-8")
    for element_id in (
        "agent-assist-enabled", "agent-assist-questions", "agent-assist-notifications",
        "agent-assist-ai", "agent-assist-save", "agent-assist-notifications-list",
        "storage-scan-enabled", "storage-scan-interval", "storage-scan-now",
        "storage-scan-results",
    ):
        assert f'id="{element_id}"' in html
    assert 'api("/api/agent-assist/settings"' in app
    assert 'api("/api/agent-assist/notification/respond"' in app
    assert 'api("/api/storage/settings"' in app
    assert 'api("/api/storage/scan"' in app
    for endpoint in (
        "/api/agent-assist/status", "/api/agent-assist/notifications",
        "/api/storage/status", "/api/agent-assist/settings",
        "/api/agent-assist/notification/respond", "/api/storage/settings",
        "/api/storage/scan",
    ):
        assert endpoint in server
    assert "agent_assist.start()" in (ROOT / "agent.py").read_text(encoding="utf-8")
    assert "storage_intelligence.start()" in (ROOT / "agent.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS agent_notifications" in assistant
    assert "CREATE TABLE IF NOT EXISTS storage_scan_history" in storage
    assert "def _agent_toast(" in assistant
    assert "Notification.requestPermission" not in assistant



def test_simple_command_home_keeps_advanced_tools_available_and_agent_backed():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    preferences = (ROOT / "sentinel" / "ui_preferences.py").read_text(encoding="utf-8")

    assert '<body class="ui-simple">' in html
    assert 'id="ui-mode-toggle"' in html
    assert 'id="cmd-agent-list"' in html
    assert 'id="cmd-agent-count"' in html
    assert 'id="cmd-agent-refresh"' in html
    assert 'id="cmd-diagnose-question"' in html
    assert 'id="cmd-diagnose-run"' in html
    assert 'id="cmd-diagnose-result"' in html
    assert 'id="cmd-storage-scan"' in html

    assert 'api("/api/ui/preferences"' in app
    assert 'apiRetry("/api/ui/preferences"' in app
    assert "function applyUiPreferences(" in app
    assert "function setUiNavigationMode(" in app
    assert "function renderCommandAssistant(" in app
    assert "function handleCommandAgentAction(" in app
    assert "function loadCommandAssistantBrief(" in app
    assert "bindWindowsDiagnosis(\"cmd-diagnose-question\",\"cmd-diagnose-run\",\"cmd-diagnose-result\")" in app
    assert 'api("/api/storage/scan"' in app
    assert 'api("/api/agent-assist/notification/respond"' in app

    assert 'body.ui-simple #nav .ng' in css
    assert 'body.ui-simple #nav button[data-v]' in css
    assert 'body.ui-simple .command-launchers' in css
    assert 'body.ui-simple .command-more-metrics' in css
    assert '"/api/ui/preferences"' in server
    assert "ui_preferences.settings()" in server
    assert "ui_preferences.update(body)" in server
    assert 'CREATE TABLE IF NOT EXISTS ui_preferences' in preferences
    assert '"navigation_mode": "simple"' in preferences



def test_full_windows_review_is_agent_owned_local_and_exposed_from_command_deck():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    assistant = (ROOT / "sentinel" / "agent_assist.py").read_text(encoding="utf-8")
    specialist = (ROOT / "sentinel" / "windows_intelligence.py").read_text(encoding="utf-8")
    collectors = (ROOT / "sentinel" / "collectors.py").read_text(encoding="utf-8")

    assert 'id="cmd-system-review"' in html
    assert 'id="agent-assist-reviews"' in html
    assert 'id="agent-assist-review-interval"' in html
    assert 'system_reviews_enabled:!!document.getElementById("agent-assist-reviews")?.checked' in app
    assert 'system_review_interval_hours:Number(document.getElementById("agent-assist-review-interval")?.value||12)' in app
    assert 'api("/api/agent-assist/system-review"' in app
    assert 'if p == "/api/agent-assist/system-review":' in server
    assert "agent_assist.request_system_review()" in server
    assert "def _maybe_system_review()" in assistant
    assert "_maybe_system_review()" in assistant
    assert "request_ai=True" in assistant
    assert "system_review_interval_hours" in assistant
    assert "runtime_engine.admit_optional_work(" in assistant

    for evidence_field in (
        "top_processes_by_resource", '"services"', '"scheduled_tasks"', '"installed_apps"',
        '"drivers"', '"driver_updates"', '"recent_events_7d"', '"application_usage_30d"',
        '"source_health"', '"prior_user_answers"', '"evidence_ids"',
    ):
        assert evidence_field in specialist
    for private_field in ("command_lines", "window_titles", "browser_content", "remote_ip_addresses"):
        assert private_field in specialist

    assert "windows_event_seen" in collectors
    assert "baseline_complete" in collectors
    assert "Microsoft-Windows-WindowsUpdateClient/Operational" in collectors
    assert "Microsoft-Windows-Kernel-PnP/Configuration" in collectors
    assert "Application Error" in collectors



def test_local_automation_builder_uses_typed_allowlisted_windows_flows():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    agent = (ROOT / "agent.py").read_text(encoding="utf-8")
    engine = (ROOT / "sentinel" / "workflow_engine.py").read_text(encoding="utf-8")

    for control in (
        'id="flow-name"', 'id="flow-trigger"', 'id="flow-action"',
        'id="flow-event-category"', 'id="flow-schedule-hours"',
        'id="flow-metric"', 'id="flow-threshold"', 'id="flow-samples"',
        'id="flow-create"', 'id="local-automation-flows"',
    ):
        assert control in html

    assert 'if p == "/api/automation/flows":' in server
    assert "workflow_engine.create_flow(body)" in server
    assert "workflow_engine.set_enabled(" in server
    assert "workflow_engine.delete_flow(" in server
    assert "workflow_engine.list_flows()" in server
    assert "workflow_engine.start()" in agent
    assert "workflow_engine.shutdown()" in agent
    assert 'api("/api/automation/flows",payload)' in app
    assert "initLocalAutomation();" in app

    assert 'TRIGGERS = frozenset({"event", "schedule", "metric"})' in engine
    assert '"local_ai_review"' in engine and '"read_only_diagnostics"' in engine
    assert '"storage_scan"' in engine and '"notify_user"' in engine
    assert "at most 20 local workflows" in engine
    assert "last_event_id" in engine and "cooldown_seconds" in engine
    assert "arbitrary commands and scripts are not accepted" in engine
    assert "subprocess" not in engine and "Popen(" not in engine



def test_component_baselines_are_agent_owned_local_and_operator_approved():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    agent = (ROOT / "agent.py").read_text(encoding="utf-8")
    engine = (ROOT / "sentinel" / "component_intelligence.py").read_text(encoding="utf-8")
    specialist = (ROOT / "sentinel" / "windows_intelligence.py").read_text(encoding="utf-8")

    for element_id in (
        "component-baseline-state", "component-baseline-refresh",
        "component-baseline-summary", "component-process-candidates",
        "component-service-candidates",
    ):
        assert f'id="{element_id}"' in html

    for ui_contract in (
        "function componentReviewCard", "function loadComponentIntelligence",
        "function initComponentIntelligence", 'initComponentIntelligence();',
        'api("/api/components/intelligence")',
        'api("/api/components/preference"',
        'api("/api/components/propose-close"',
        'api("/api/components/refresh"',
        "EVIDENCE COVERAGE",
        "data-component-note",
        "SAVE NOTE", "EVIDENCE COVERAGE",
        "PREPARE GRACEFUL CLOSE",
    ):
        assert ui_contract in app

    assert ".component-review-card" in css
    assert ".component-review-note" in css
    assert 'if p == "/api/components/intelligence":' in server
    assert 'if p == "/api/components/preference":' in server
    assert 'if p == "/api/components/propose-close":' in server
    assert "component_intelligence.propose_graceful_close(" in server
    assert 'note_only' in engine
    assert 'operator_component_preferences' in engine
    assert "component_intelligence.start()" in agent
    assert "component_intelligence.shutdown()" in agent

    assert "_PROCESS_SAMPLE_SECONDS = 300" in engine
    assert "_SERVICE_SAMPLE_SECONDS = 900" in engine
    assert "_RETENTION_SECONDS = 30 * 86400" in engine
    assert "_BASELINE_MIN_DAYS = 7" in engine
    assert "visible_sample_ratio" in engine and "onscreen_sample_ratio" in engine
    assert "visible_ratio > 0.05 or onscreen_ratio > 0.02" in engine
    assert "evidence_confidence_score" in engine
    assert "resource_impact_score" in engine and "review_priority_score" in engine
    assert "publisher_consistency" in engine and "_certificate_organization" in engine
    assert "def _current_interactive_instance" in engine
    assert "or core.STATE.get(\"game\")" in engine
    assert "component_score_semantics" in specialist
    assert "not a probability" in engine
    assert "not a probability" in html
    assert "Get-AuthenticodeSignature" in engine
    assert "ServicesDependedOn" in engine and "DependentServices" in engine
    assert "binary_path" in engine
    assert 'if key not in ("binary_path", "description")' in engine
    assert "process_component_id" in engine and "hashlib.sha256" in engine
    assert "def set_preference(" in engine
    assert "def propose_graceful_close(" in engine
    assert 'actions.propose(\n        "terminate_process"' in engine
    assert "TerminateProcess" not in engine
    assert "process.close" not in engine
    assert "ai_evidence()" in specialist
    assert "service_dependency_graph" in specialist
    assert "operator_note" in specialist
    assert "Longitudinal component baselines" in specialist



def test_startup_and_scheduled_task_provenance_is_local_and_argument_free():
    inventory = (ROOT / "sentinel" / "inventory.py").read_text(encoding="utf-8")
    components = (ROOT / "sentinel" / "component_intelligence.py").read_text(encoding="utf-8")
    specialist = (ROOT / "sentinel" / "windows_intelligence.py").read_text(encoding="utf-8")

    assert "action_binaries=@($actions | Sort-Object -Unique | Select-Object -First 6)" in inventory
    assert "action_count=@($_.Actions).Count" in inventory
    assert "startup_task_relationships()" in components
    assert '"command_arguments_collected": False' in components
    assert '"startup_task_relationships": component_evidence.get("startup_task_relationships", [])' in specialist
    assert '"startup_task_relationships": rows("startup_task_relationships", 36' in specialist
    assert "startup_task_relationships" in specialist[specialist.index("trim_targets ="):specialist.index("for key, minimum in trim_targets")]
    assert 'raw.get("arguments")' not in components[components.index("def startup_task_relationships"):components.index("def ai_evidence")]
