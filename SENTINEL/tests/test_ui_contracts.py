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
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    assert 'id="adv-provider-install"' in html
    assert 'id="adv-sensor-inventory"' in html
    assert 'api("/api/hardware/provider/start"' in app

    for element_id in ("bootProgress", "bootPct", "bootStage", "bootDetail", "bootGauge", "bootRetry"):
        assert f'id="{element_id}"' in html
    for removed_id in (
        "bootLog", "bootModules", "bootCpuValue", "bootRamValue",
        "bootGpuValue", "bootDpcValue", "bootProcessCount",
    ):
        assert f'id="{removed_id}"' not in html
    assert "WINDOWS PROCESS FIELD" not in html
    assert "data-boot-step=" in html
    assert "class=\"boot-suit-figure\"" in html
    assert "function showBootRetry(" in app
    assert 'retry.onclick = () => location.reload()' in app
    assert "endBoot();" not in app[app.index('boot().catch(error =>'):]
    assert "bootSkip" not in html + app + css
    assert "SKIP INTRO" not in html + app + css
    assert "API_CONCURRENCY = 3" in app
    assert "API_TIMEOUT_MS = 16000" in app
    assert 'apiRetry("/api/boot", 1)' in app
    assert 'apiRetry("/api/history?secs=300", 1)' in app
    assert 'apiRetry("/api/events?limit=120", 1)' in app
    assert "await runPool(jobs)" not in app
    assert "await runPool(secondaryJobs)" not in app
    assert "function starfield()" not in app
    assert "updateBootTelemetry" not in app
    assert "function boot_snapshot()" in server
    assert 'if p == "/api/boot":' in server
    assert "def agent_runtime(" not in server[server.index("def boot_snapshot()"):server.index("class H(")]
    assert "Promise.allSettled([" in app
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
    assert ".boot-console" in css and ".boot-suit-figure" in css
    assert ".boot-live-readouts" not in cssAppend
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
    assert 'id="adv-etw-interval"' in html
    assert "etw_auto_interval_s" in app
