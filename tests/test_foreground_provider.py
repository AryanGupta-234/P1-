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
    )

    first = list(provider.collect_snapshot())
    second = list(provider.collect_snapshot())

    assert len(first) == 1
    assert second == []
    assert first[0].event_type == "window.foreground_changed"
    assert first[0].data["process_name"] == "msedge.exe"
    assert first[0].data["pid"] == 4001


def test_window_title_is_not_requested_or_stored_by_default():
    api = FakeForegroundApi()
    provider = WindowsForegroundProvider(api=api, process_lookup=lambda pid: "chrome.exe")

    event = list(provider.collect_snapshot())[0]

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

    event = list(provider.collect_snapshot())[0]

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

    assert len(first) == len(second) == 1
    assert first[0].entity.stable_id == "101"
    assert second[0].entity.stable_id == "202"


def test_no_foreground_window_emits_nothing():
    api = FakeForegroundApi()
    api.hwnd = None
    provider = WindowsForegroundProvider(api=api)

    assert list(provider.collect_snapshot()) == []
