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
    assert '$("[data-command-route]")' in app
    assert 'data-command-route="activityx"' in html
    assert "$$([\"data-command-route\"])" in app
    assert 'class="command-more-metrics"' in html
    assert "function renderCommandVisuals()" in app
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
    assert 'id="adv-etw-interval"' in html
    assert "etw_auto_interval_s" in app
