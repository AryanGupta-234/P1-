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
    for element_id in ("bootProgress", "bootPct", "bootStage", "bootDetail", "bootLog", "bootModules"):
        assert f'id="{element_id}"' in html
    assert "bootSkip" not in html + app + css
    assert "SKIP INTRO" not in html + app + css
    assert 'new Set(["command", "net"])' in app
    assert "const minSplashMs = 120" in app
    assert 'new Set(["command", "net"])' in app
    assert "const minSplashMs = 120" in app
    assert 'data-adv-tab="overview"' in html
    assert "PAGE_WARMED" in app and "PAGE_WARM_TTL_MS" in app
    assert "data-boot-module" in app
    assert ".boot-console" in css and ".boot-module.loading" in css
    assert "overflow-wrap:anywhere" in css
    assert "panelGlassSheen" in css and "ambientGridDrift" in css
    assert "boot().catch(error =>" in app
    assert "Remote Web Server > Run" not in app
    assert "SENSOR FEED" in app
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
