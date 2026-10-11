"""Opt-in bounded systemwide process-resource snapshots for Windows."""
from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import psutil

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


class WindowsProcessResourceProvider:
    """Sample process CPU/RSS/thread/I/O counters without inspecting process content.

    The provider scans process metadata, samples no more than max_processes per
    poll, and emits one compact top-consumer snapshot. It never reads command
    lines, executable paths, environment variables, handles or window content.
    """

    name = "windows.process_resources"

    def __init__(
        self,
        *,
        max_processes: int = 256,
        top_processes: int = 20,
        sample_interval: float = 10.0,
        process_iter: Callable[[], Iterable[Any]] | None = None,
        logical_cpu_count: Callable[[], int | None] = lambda: psutil.cpu_count(logical=True),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if os.name != "nt":
            raise OSError("Systemwide process-resource sampling requires native Windows.")
        if not 1 <= max_processes <= 512:
            raise ValueError("max_processes must be between 1 and 512")
        if not 1 <= top_processes <= 50:
            raise ValueError("top_processes must be between 1 and 50")
        if not 2.0 <= sample_interval <= 300.0:
            raise ValueError("sample_interval must be between 2 and 300 seconds")

        self.max_processes = max_processes
        self.top_processes = top_processes
        self.sample_interval = sample_interval
        self._process_iter = process_iter or (
            lambda: psutil.process_iter(
                attrs=["pid", "name", "create_time"],
                ad_value=None,
            )
        )
        self._logical_cpu_count = logical_cpu_count
        self._clock = clock
        self._last_sample = float("-inf")
        self._process_state: dict[int, tuple[float, Any]] = {}

    @staticmethod
    def _safe_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    @staticmethod
    def _safe_float(value: object, *, minimum: float = 0.0) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = float(value)
        if not math.isfinite(result) or result < minimum:
            return None
        return result

    def collect_snapshot(self) -> list[AIEEvent]:
        """Return an aggregated process snapshot on the configured cadence."""
        now = self._clock()
        if now - self._last_sample < self.sample_interval:
            return []
        self._last_sample = now

        try:
            logical_cpus = max(1, self._logical_cpu_count() or 1)
        except (OSError, TypeError, ValueError):
            logical_cpus = 1

        observed_count = 0
        next_state: dict[int, tuple[float, Any]] = {}
        sampled: list[dict[str, object]] = []
        truncated = False

        try:
            iterator = self._process_iter()
            for candidate in iterator:
                info = getattr(candidate, "info", None)
                if not isinstance(info, dict):
                    continue
                pid = self._safe_int(info.get("pid"))
                name = info.get("name")
                create_time = self._safe_float(info.get("create_time"))
                if pid is None or pid <= 0 or not isinstance(name, str) or not name:
                    continue
                observed_count += 1
                if len(sampled) >= self.max_processes:
                    truncated = True
                    continue
                process = candidate
                previous = self._process_state.get(pid)
                if previous is not None and previous[0] == create_time:
                    process = previous[1]
                    try:
                        raw_cpu = process.cpu_percent(interval=None)
                        cpu_pct = self._safe_float(raw_cpu)
                        if cpu_pct is not None:
                            cpu_pct = min(100.0, cpu_pct / logical_cpus)
                    except (psutil.Error, OSError, ValueError):
                        cpu_pct = None
                else:
                    try:
                        process.cpu_percent(interval=None)
                    except (psutil.Error, OSError, ValueError):
                        pass
                    cpu_pct = None

                try:
                    memory = process.memory_info()
                    rss_bytes = self._safe_int(memory.rss)
                except (psutil.Error, OSError, AttributeError):
                    rss_bytes = None
                try:
                    threads = self._safe_int(process.num_threads())
                except (psutil.Error, OSError, AttributeError):
                    threads = None
                try:
                    counters = process.io_counters()
                    read_bytes = self._safe_int(counters.read_bytes)
                    write_bytes = self._safe_int(counters.write_bytes)
                except (psutil.Error, OSError, AttributeError):
                    read_bytes = None
                    write_bytes = None

                next_state[pid] = (create_time, process)
                sampled.append({
                    "pid": pid,
                    "process_name": name[:120],
                    "create_time": create_time,
                    "cpu_pct_total_capacity": cpu_pct,
                    "memory_rss_bytes": rss_bytes,
                    "thread_count": threads,
                    "io_read_bytes": read_bytes,
                    "io_write_bytes": write_bytes,
                })
        except (psutil.Error, OSError, RuntimeError):
            # A transient global process-enumeration failure is a non-fatal missed sample.
            return []

        self._process_state = next_state
        known_cpu = [
            item for item in sampled
            if isinstance(item["cpu_pct_total_capacity"], (int, float))
        ]
        known_cpu.sort(
            key=lambda item: (
                float(item["cpu_pct_total_capacity"]),
                int(item["memory_rss_bytes"] or 0),
            ),
            reverse=True,
        )
        if not known_cpu:
            sampled.sort(
                key=lambda item: int(item["memory_rss_bytes"] or 0),
                reverse=True,
            )
            top = sampled[: self.top_processes]
        else:
            top = known_cpu[: self.top_processes]

        return [AIEEvent(
            timestamp=datetime.now(timezone.utc),
            host_id=host_id(),
            source=self.name,
            event_type="process.system_resource_snapshot",
            entity=EntityRef(type="host_process_set", name="top_process_consumers"),
            data={
                "total_processes_seen": observed_count,
                "sampled_processes": len(sampled),
                "reported_processes": len(top),
                "truncated": truncated,
                "max_processes": self.max_processes,
                "logical_cpu_count": logical_cpus,
                "cpu_metric": "percent_of_total_logical_cpu_capacity",
                "command_lines_collected": False,
                "executable_paths_collected": False,
                "processes": top,
            },
            sensitivity="internal",
            confidence=0.95,
            evidence_kind="observed",
        )]
