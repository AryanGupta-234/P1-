from types import SimpleNamespace

import pytest

from aie.providers.process_resources import WindowsProcessResourceProvider


class FakeProcess:
    def __init__(self, pid, name, create_time, *, cpu_values=None, rss=1000):
        self.info = {"pid": pid, "name": name, "create_time": create_time}
        self.cpu_values = list(cpu_values or [0.0, 0.0])
        self.cpu_calls = 0
        self.rss = rss

    def cpu_percent(self, interval=None):
        value = self.cpu_values[min(self.cpu_calls, len(self.cpu_values) - 1)]
        self.cpu_calls += 1
        return value

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def num_threads(self):
        return 10

    def io_counters(self):
        return SimpleNamespace(read_bytes=100, write_bytes=200)


def make_provider(clock, processes, **kwargs):
    return WindowsProcessResourceProvider(
        max_processes=kwargs.get("max_processes", 10),
        top_processes=kwargs.get("top_processes", 5),
        sample_interval=kwargs.get("sample_interval", 5.0),
        process_iter=lambda: iter(processes),
        logical_cpu_count=lambda: 2,
        clock=lambda: clock[0],
    )


def test_system_process_snapshot_is_throttled_and_reports_top_processes():
    clock = [100.0]
    one = FakeProcess(10, "browser.exe", 100.0, cpu_values=[0.0, 80.0], rss=5000)
    two = FakeProcess(11, "worker.exe", 101.0, cpu_values=[0.0, 20.0], rss=3000)
    processes = [one, two]
    provider = make_provider(clock, processes)

    first = provider.collect_snapshot()
    assert len(first) == 1
    assert first[0].data["reported_processes"] == 2
    assert all(item["cpu_pct_total_capacity"] is None for item in first[0].data["processes"])

    assert provider.collect_snapshot() == []
    clock[0] += 6.0
    second = provider.collect_snapshot()
    top = second[0].data["processes"]

    assert top[0]["process_name"] == "browser.exe"
    assert top[0]["cpu_pct_total_capacity"] == 40.0
    assert top[1]["cpu_pct_total_capacity"] == 10.0
    assert second[0].data["command_lines_collected"] is False
    assert second[0].data["executable_paths_collected"] is False


def test_system_process_sample_is_bounded_and_marks_truncation():
    clock = [100.0]
    processes = [
        FakeProcess(pid, f"app{pid}.exe", float(pid), rss=pid * 100)
        for pid in range(1, 6)
    ]
    provider = make_provider(
        clock,
        processes,
        max_processes=3,
        top_processes=2,
    )

    result = provider.collect_snapshot()

    assert len(result) == 1
    assert result[0].data["total_processes_seen"] == 5
    assert result[0].data["sampled_processes"] == 3
    assert result[0].data["reported_processes"] == 2
    assert result[0].data["truncated"] is True
    assert len(result[0].data["processes"]) == 2


def test_system_process_reuse_detects_pid_recycle_and_reprimes_cpu():
    clock = [100.0]
    old = FakeProcess(77, "old.exe", 100.0, cpu_values=[0.0, 40.0])
    new = FakeProcess(77, "new.exe", 200.0, cpu_values=[0.0, 60.0])
    current = [old]
    provider = WindowsProcessResourceProvider(
        max_processes=10,
        top_processes=5,
        sample_interval=2.0,
        process_iter=lambda: iter(current),
        logical_cpu_count=lambda: 2,
        clock=lambda: clock[0],
    )

    first = provider.collect_snapshot()
    assert first[0].data["processes"][0]["cpu_pct_total_capacity"] is None
    clock[0] += 3
    assert provider.collect_snapshot()[0].data["processes"][0]["cpu_pct_total_capacity"] == 20.0

    current[:] = [new]
    clock[0] += 3
    recycled = provider.collect_snapshot()[0]
    assert recycled.data["processes"][0]["process_name"] == "new.exe"
    assert recycled.data["processes"][0]["cpu_pct_total_capacity"] is None


def test_system_process_provider_rejects_unbounded_configuration():
    with pytest.raises(ValueError):
        WindowsProcessResourceProvider(max_processes=10000)
    with pytest.raises(ValueError):
        WindowsProcessResourceProvider(top_processes=1000)
