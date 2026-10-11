import threading

import pytest

from aie.providers.uia import WindowsUIATreeProvider


class FakeForegroundApi:
    def __init__(self):
        self.hwnd = 101
        self.pid = 4001

    def foreground_window(self):
        return self.hwnd

    def process_id(self, hwnd):
        return self.pid

    def window_class(self, hwnd):
        return "WindowClass"

    def window_title(self, hwnd):
        raise AssertionError("UIA provider must not read window titles")


class FakeReader:
    def __init__(self, nodes=None):
        self.nodes = nodes or [{
            "index": 0,
            "parent_index": None,
            "depth": 0,
            "control_type": "Window",
            "class_name": "Chrome_WidgetWin_1",
            "automation_id": "BrowserRoot",
            "rectangle": [0, 0, 1280, 720],
            "visible": True,
            "enabled": True,
            "focusable": True,
            "name": "PRIVATE DOCUMENT CONTENT MUST NOT BE STORED",
            "value": "password field text must not be stored",
        }]

    def read_tree(self, hwnd, *, max_nodes, max_depth):
        assert max_nodes > 0
        assert max_depth > 0
        return self.nodes


def provider(reader=None, *, app="msedge.exe", allowed_apps=None, clock=None, timeout=0.2):
    return WindowsUIATreeProvider(
        allowed_process_names=allowed_apps if allowed_apps is not None else {app},
        reader=reader or FakeReader(),
        api=FakeForegroundApi(),
        process_lookup=lambda pid: app,
        max_nodes=10,
        max_depth=3,
        sample_interval=10,
        timeout_seconds=timeout,
        clock=clock or (lambda: 100.0),
    )


def test_uia_tree_is_allowlisted_and_does_not_capture_text():
    monitor = provider()
    events = monitor.collect_snapshot()

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "window.uia_tree_snapshot"
    assert event.data["text_collected"] is False
    assert event.data["screenshot_collected"] is False
    assert event.data["nodes"][0]["control_type"] == "Window"
    assert "name" not in event.data["nodes"][0]
    assert "value" not in event.data["nodes"][0]


def test_uia_refuses_empty_allowlist():
    with pytest.raises(ValueError, match="allowlisted"):
        WindowsUIATreeProvider(
            allowed_process_names=set(),
            reader=FakeReader(),
            api=FakeForegroundApi(),
        )


def test_uia_ignores_non_allowlisted_foreground_app():
    monitor = provider(app="notepad.exe", allowed_apps={"chrome.exe"})
    assert monitor.collect_snapshot() == []


def test_uia_sampling_is_throttled_for_same_window():
    clock_now = [100.0]
    monitor = provider(clock=lambda: clock_now[0])
    assert len(monitor.collect_snapshot()) == 1
    assert monitor.collect_snapshot() == []
    clock_now[0] += 11
    assert len(monitor.collect_snapshot()) == 1


def test_uia_tree_rejects_unbounded_or_malformed_nodes():
    reader = FakeReader(nodes=[
        {
            "index": 0,
            "depth": 0,
            "control_type": "Pane",
            "rectangle": [0, 0, 10, 10],
            "visible": True,
            "enabled": True,
        },
        "not-a-node",
    ])
    monitor = provider(reader)
    events = monitor.collect_snapshot()

    assert events[0].data["node_count"] == 1


def test_uia_scan_timeout_does_not_accumulate_worker_threads():
    started = threading.Event()
    release = threading.Event()

    class SlowReader:
        def read_tree(self, hwnd, *, max_nodes, max_depth):
            started.set()
            release.wait(1.0)
            return [{
                "index": 0,
                "depth": 0,
                "control_type": "Window",
                "class_name": "Test",
                "automation_id": "",
                "rectangle": [0, 0, 10, 10],
                "visible": True,
                "enabled": True,
                "focusable": False,
            }]

    clock_now = [100.0]
    monitor = provider(reader=SlowReader(), timeout=0.1, clock=lambda: clock_now[0])
    first = monitor.collect_snapshot()
    assert len(first) == 1
    assert first[0].event_type == "windows.uia.provider_timeout"
    assert first[0].data["reason_code"] == "scan_timeout_or_busy"
    assert started.wait(1.0)
    clock_now[0] += 11.0
    assert monitor.collect_snapshot() == []
    release.set()
    assert monitor._scan_lock.acquire(timeout=1.0)
    monitor._scan_lock.release()
    clock_now[0] += 11.0
    recovered = monitor.collect_snapshot()
    assert recovered[0].event_type == "windows.uia.provider_recovered"
    assert any(event.event_type == "window.uia_tree_snapshot" for event in recovered)
