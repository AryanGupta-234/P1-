from pathlib import Path

from aie import runtime


class FakeWindowsProvider:
    def __init__(self):
        self.calls = 0

    def collect_snapshot(self, *, include_host=True):
        self.calls += 1
        return []


def install_fake_clock(monkeypatch):
    state = {"now": 0.0}

    def monotonic():
        return state["now"]

    def sleep(seconds):
        state["now"] += seconds

    monkeypatch.setattr(runtime.time, "monotonic", monotonic)
    monkeypatch.setattr(runtime.time, "sleep", sleep)


def test_paused_observer_collects_no_events(tmp_path: Path, monkeypatch):
    provider = FakeWindowsProvider()
    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: True)

    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=tmp_path / "paused.sqlite3",
        include_network=False,
        include_foreground=False,
    )

    assert total == 0
    assert provider.calls == 0


def test_unpaused_observer_resumes_sampling(tmp_path: Path, monkeypatch):
    provider = FakeWindowsProvider()
    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=tmp_path / "running.sqlite3",
        include_network=False,
        include_foreground=False,
    )

    assert total == 0
    assert provider.calls == 2
