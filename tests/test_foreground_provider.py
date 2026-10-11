from types import SimpleNamespace

import pytest

from aie.providers.foreground import WindowsForegroundProvider


class FakeForegroundApi:
    def __init__(self):
        self.hwnd = 101
        self.pid = 4001
        self.title_calls = 0

    def foreground_window(self):
        return self.hwnd

    def process_id(self, hwnd):
        return self.pid

    def window_class(self, hwnd):
        return "Chrome_WidgetWin_1"

    def window_title(self, hwnd):
        self.title_calls += 1
        return "Private document - Browser"


def test_foreground_observer_emits_only_on_change():
    api = FakeForegroundApi()
    provider = WindowsForegroundProvider(
        api=api,
        process_lookup=lambda pid: "msedge.exe",
        process_factory=lambda pid: FakeProcess(),
    )

    first = list(provider.collect_snapshot())
    second = list(provider.collect_snapshot())

    transition = next(event for event in first if event.event_type == "window.foreground_changed")
    assert second == []
    assert transition.data["process_name"] == "msedge.exe"
    assert transition.data["pid"] == 4001
    assert any(event.event_type == "process.foreground_resource_sample" for event in first)


def test_window_title_is_not_requested_or_stored_by_default():
    api = FakeForegroundApi()
    provider = WindowsForegroundProvider(api=api, process_lookup=lambda pid: "chrome.exe")

    event = next(
        event for event in provider.collect_snapshot()
        if event.event_type == "window.foreground_changed"
    )

    assert api.title_calls == 0
    assert "window_title" not in event.data
    assert event.data["window_title_collected"] is False
    assert event.sensitivity == "internal"


def test_window_title_requires_explicit_opt_in_and_marks_event_sensitive():
    api = FakeForegroundApi()
    provider = WindowsForegroundProvider(
        api=api,
        process_lookup=lambda pid: "chrome.exe",
        include_window_titles=True,
    )

    event = next(
        event for event in provider.collect_snapshot()
        if event.event_type == "window.foreground_changed"
    )

    assert api.title_calls == 1
    assert event.data["window_title"] == "Private document - Browser"
    assert event.sensitivity == "sensitive"


def test_foreground_transition_creates_new_event():
    api = FakeForegroundApi()
    provider = WindowsForegroundProvider(api=api, process_lookup=lambda pid: "app.exe")

    first = list(provider.collect_snapshot())
    api.hwnd = 202
    api.pid = 5002
    second = list(provider.collect_snapshot())
    first_transition = next(event for event in first if event.event_type == "window.foreground_changed")
    second_transition = next(event for event in second if event.event_type == "window.foreground_changed")

    assert first_transition.entity.stable_id == "101"
    assert second_transition.entity.stable_id == "202"


def test_no_foreground_window_emits_nothing():
    api = FakeForegroundApi()
    api.hwnd = None
    provider = WindowsForegroundProvider(api=api)

    assert list(provider.collect_snapshot()) == []



class FakeProcess:
    def __init__(self):
        self.cpu_calls = 0

    def create_time(self):
        return 1234.5

    def cpu_percent(self, interval=None):
        self.cpu_calls += 1
        return 18.5 if self.cpu_calls > 1 else 0.0

    def memory_info(self):
        return SimpleNamespace(rss=1024 * 1024 * 120)

    def num_threads(self):
        return 24

    def io_counters(self):
        return SimpleNamespace(read_bytes=1000, write_bytes=2000)


def test_foreground_resource_samples_are_throttled_and_pid_scoped():
    api = FakeForegroundApi()
    clock_state = [100.0]
    process = FakeProcess()
    created = []

    def process_factory(pid):
        created.append(pid)
        return process

    provider = WindowsForegroundProvider(
        api=api,
        process_lookup=lambda pid: "msedge.exe",
        process_factory=process_factory,
        clock=lambda: clock_state[0],
        resource_sample_interval=5.0,
    )

    first = list(provider.collect_snapshot())
    first_sample = next(
        event for event in first if event.event_type == "process.foreground_resource_sample"
    )
    assert first_sample.data["cpu_pct"] is None
    assert first_sample.data["memory_rss_bytes"] == 120 * 1024 * 1024
    assert first_sample.data["thread_count"] == 24
    assert first_sample.data["io_read_bytes"] == 1000

    clock_state[0] = 102.0
    assert list(provider.collect_snapshot()) == []

    clock_state[0] = 106.0
    next_events = list(provider.collect_snapshot())
    second_sample = next(
        event for event in next_events
        if event.event_type == "process.foreground_resource_sample"
    )
    assert second_sample.data["cpu_pct"] == 18.5
    assert created == [4001]


def test_resource_sampling_interval_must_be_bounded():
    with pytest.raises(ValueError):
        WindowsForegroundProvider(
            api=FakeForegroundApi(),
            resource_sample_interval=0.1,
        )
