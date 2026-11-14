from senti.environment import EnvironmentMonitor, Thresholds, register_environment_tools
from senti.store import UnifiedDataStore
from senti.tools.registry import CapabilityRegistry


def sample(**overrides):
    base = {"at": "2026-11-14T10:00:00+00:00", "cpu_percent": 10.0, "memory_percent": 50.0,
            "memory_available_gb": 8.0, "disks": [{"mount": "C:\\", "free_gb": 120.0, "free_percent": 40.0}],
            "battery": {"percent": 80, "plugged": True}, "network_online": True, "foreground_app": "Code.exe"}
    base.update(overrides)
    return base


class Feed:
    def __init__(self, *samples):
        self.samples = list(samples)

    def __call__(self):
        return self.samples.pop(0) if len(self.samples) > 1 else self.samples[0]


def make(tmp_path, *samples, events=None, clock=None, checks=None):
    return EnvironmentMonitor(UnifiedDataStore(tmp_path / "s.sqlite3"), event_sink=(events.append if events is not None else None),
                              sampler=Feed(*samples), thresholds=Thresholds(sustained_samples=3),
                              clock=clock or (lambda: 0.0), extra_checks=checks)


def test_sustained_memory_pressure_raises_one_insight_with_read_only_suggestion(tmp_path):
    events = []
    low = sample(memory_available_gb=0.8, memory_percent=95.0)
    monitor = make(tmp_path, low, events=events)
    assert monitor.tick() == [] and monitor.tick() == []  # not yet sustained
    raised = monitor.tick()
    assert [i["title"] for i in raised] == ["Memory is running low"]
    assert raised[0]["suggestion"] == {"tool": "senti_list_processes", "arguments": {"sort_by": "memory"}}
    assert monitor.tick() == []  # deduplicated while it persists
    assert events[-1]["type"] == "insight" and events[-1]["status"] == "open"
    assert monitor.insights()[0]["severity"] == "warning"


def test_condition_clearing_resolves_the_insight(tmp_path):
    events = []
    low = sample(memory_available_gb=0.5)
    monitor = make(tmp_path, low, low, low, sample(), events=events)
    for _ in range(3):
        monitor.tick()
    assert monitor.insights()
    monitor.tick()  # healthy sample
    assert monitor.insights() == []
    assert any(e["type"] == "insight" and e["status"] == "resolved" for e in events)


def test_disk_battery_and_network_conditions(tmp_path):
    monitor = make(tmp_path, sample(),
                   sample(disks=[{"mount": "C:\\", "free_gb": 3.0, "free_percent": 2.0}],
                          battery={"percent": 12, "plugged": False}, network_online=False))
    monitor.tick()
    titles = {i["title"] for i in monitor.tick()}
    assert {"Drive C:\\ is nearly full", "Battery is low", "Network connection dropped"} <= titles


def test_extra_checks_feed_reminders_and_dismiss(tmp_path):
    reminder = {"key": "reminder:1", "severity": "info", "title": "Reminder", "detail": "Call the ISP",
                "source": "reminder", "suggestion": None}
    fired = [[reminder], []]
    monitor = make(tmp_path, sample(), checks=[lambda: fired.pop(0) if fired else []])
    raised = monitor.tick()
    assert raised[0]["detail"] == "Call the ISP"
    assert monitor.dismiss(raised[0]["insight_id"]) is True
    assert monitor.insights() == []


def test_context_tool_reports_names_only_and_trend(tmp_path):
    monitor = make(tmp_path, sample(foreground_app="Code.exe"), sample(foreground_app="chrome.exe"))
    monitor.tick()
    monitor.tick()
    registry = CapabilityRegistry()
    register_environment_tools(registry, monitor)
    result = registry.dispatch("senti_get_environment_context", {})
    assert result.status == "succeeded"
    assert [a["app"] for a in result.data["recent_foreground_apps"]] == ["Code.exe", "chrome.exe"]
    assert "trend_last_samples" in result.data


def test_real_sampler_runs_on_this_machine():
    from senti.environment import default_sampler
    data = default_sampler()
    assert 0 <= data["memory_percent"] <= 100 and isinstance(data["disks"], list)
