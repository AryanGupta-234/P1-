"""Environment awareness and proactive insights.

A bounded background sampler keeps a short in-memory picture of the PC: CPU, memory,
disk, battery, network reachability and the foreground application *name* (never window
titles or content). Policy thresholds turn sustained conditions into insights, e.g. memory
pressure or low disk, plus due reminders and tasks. Each insight carries a *suggested* read-only
next step. Suggestions are never executed automatically: SENTI proposes, sir decides.

Privacy: samples live in memory (ring buffer); only insights are persisted. Disable with
``SENTI_OBSERVE=false``.
"""
from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from senti.events import EventSink, emit

_SCHEMA = """
CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY, insight_key TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
    detail TEXT NOT NULL, source TEXT NOT NULL, suggestion_json TEXT, status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_insights_status ON insights(status, updated_at);
"""


@dataclass(frozen=True)
class Thresholds:
    """Policy for when a condition deserves sir's attention (configurable, not behaviour)."""
    memory_available_gb: float = 1.5
    memory_percent: float = 92.0
    cpu_percent: float = 90.0
    sustained_samples: int = 3
    disk_free_percent: float = 8.0
    disk_free_gb: float = 5.0
    battery_percent: int = 20
    repeat_after_seconds: float = 1800.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _foreground_app() -> str | None:
    """Name of the foreground application's executable (no title, no content)."""
    if os.name != "nt":
        return None
    try:
        import psutil
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name() if pid.value else None
    except Exception:  # noqa: BLE001 - foreground lookup is best effort
        return None


def default_sampler() -> dict[str, Any]:
    import psutil
    vm = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append({"mount": part.mountpoint, "free_gb": round(usage.free / 1_073_741_824, 1),
                      "free_percent": round(100 - usage.percent, 1)})
    battery = psutil.sensors_battery()
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    online = any(
        s.isup and any(a.family == 2 and not a.address.startswith(("127.", "169.254.")) for a in addrs.get(n, []))
        for n, s in stats.items()
    )
    return {
        "at": _now(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": vm.percent,
        "memory_available_gb": round(vm.available / 1_073_741_824, 2),
        "disks": disks,
        "battery": ({"percent": battery.percent, "plugged": battery.power_plugged} if battery else None),
        "network_online": online,
        "foreground_app": _foreground_app(),
    }


class EnvironmentMonitor:
    def __init__(self, store, *, event_sink: EventSink | None = None,
                 sampler: Callable[[], dict[str, Any]] = default_sampler, interval: float = 30.0,
                 thresholds: Thresholds = Thresholds(), clock: Callable[[], float] = time.monotonic,
                 extra_checks: list[Callable[[], list[dict[str, Any]]]] | None = None):
        self.store = store
        self.event_sink = event_sink
        self.sampler = sampler
        self.interval = max(5.0, float(interval))
        self.thresholds = thresholds
        self.clock = clock
        self.extra_checks = list(extra_checks or [])
        self.samples: deque[dict[str, Any]] = deque(maxlen=120)
        self.app_history: deque[tuple[str, str]] = deque(maxlen=40)
        self._raised: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        with store.connect() as db:
            db.executescript(_SCHEMA)

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="senti-environment", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the monitor must never take SENTI down
                pass
            self._stop.wait(self.interval)

    # -------------------------------------------------------------- sampling
    def tick(self) -> list[dict[str, Any]]:
        sample = self.sampler()
        with self._lock:
            self.samples.append(sample)
            app = sample.get("foreground_app")
            if app and (not self.app_history or self.app_history[-1][1] != app):
                self.app_history.append((sample.get("at", _now()), app))
        raised = []
        for candidate in self._evaluate() + self._extra():
            insight = self._raise(candidate)
            if insight:
                raised.append(insight)
        return raised

    def _sustained(self, predicate: Callable[[dict[str, Any]], bool]) -> bool:
        recent = list(self.samples)[-self.thresholds.sustained_samples:]
        return len(recent) >= self.thresholds.sustained_samples and all(predicate(s) for s in recent)

    def _evaluate(self) -> list[dict[str, Any]]:
        t = self.thresholds
        found: list[dict[str, Any]] = []
        if not self.samples:
            return found
        last = self.samples[-1]
        if self._sustained(lambda s: s.get("memory_available_gb", 99) < t.memory_available_gb
                           or s.get("memory_percent", 0) > t.memory_percent):
            found.append({"key": "memory_pressure", "severity": "warning", "title": "Memory is running low",
                          "detail": f"{last.get('memory_percent')}% used, {last.get('memory_available_gb')} GB free "
                                    f"for the last {t.sustained_samples} samples.",
                          "suggestion": {"tool": "senti_list_processes", "arguments": {"sort_by": "memory"}}})
        if self._sustained(lambda s: s.get("cpu_percent", 0) > t.cpu_percent):
            found.append({"key": "cpu_saturated", "severity": "warning", "title": "CPU has been saturated",
                          "detail": f"CPU above {t.cpu_percent:.0f}% for {t.sustained_samples} samples.",
                          "suggestion": {"tool": "senti_list_processes", "arguments": {"sort_by": "cpu"}}})
        for disk in last.get("disks") or []:
            if disk["free_percent"] < t.disk_free_percent or disk["free_gb"] < t.disk_free_gb:
                found.append({"key": f"disk_low:{disk['mount']}", "severity": "warning",
                              "title": f"Drive {disk['mount']} is nearly full",
                              "detail": f"{disk['free_gb']} GB ({disk['free_percent']}%) free.",
                              "suggestion": {"tool": "senti_get_storage_summary", "arguments": {}}})
        battery = last.get("battery")
        if battery and not battery.get("plugged") and battery.get("percent", 100) <= t.battery_percent:
            found.append({"key": "battery_low", "severity": "info", "title": "Battery is low",
                          "detail": f"{battery['percent']}% remaining on battery.",
                          "suggestion": {"tool": "senti_list_power_plans", "arguments": {}}})
        if len(self.samples) >= 2 and self.samples[-2].get("network_online") and not last.get("network_online"):
            found.append({"key": "network_down", "severity": "warning", "title": "Network connection dropped",
                          "detail": "No adapter has a usable IPv4 address any more.",
                          "suggestion": {"tool": "senti_get_network_summary", "arguments": {}}})
        active = {c["key"] for c in found}
        for key in list(self._raised):
            if key not in active and not key.startswith(("reminder:", "task_due:")):
                self._resolve(key)
        return found

    def _extra(self) -> list[dict[str, Any]]:
        out = []
        for check in self.extra_checks:
            try:
                out.extend(check())
            except Exception:  # noqa: BLE001
                continue
        return out

    # -------------------------------------------------------------- insights
    def _raise(self, c: dict[str, Any]) -> dict[str, Any] | None:
        now = self.clock()
        last = self._raised.get(c["key"])
        if last is not None and now - last < self.thresholds.repeat_after_seconds:
            return None
        self._raised[c["key"]] = now
        insight = {"insight_id": str(uuid4()), "severity": c["severity"], "title": c["title"],
                   "detail": c["detail"], "source": c.get("source", "environment"),
                   "suggestion": c.get("suggestion"), "status": "open"}
        with self.store.connect() as db:
            db.execute("UPDATE insights SET status='resolved', updated_at=? WHERE insight_key=? AND status='open'",
                       (_now(), c["key"]))
            db.execute("INSERT INTO insights(insight_id, insight_key, severity, title, detail, source, suggestion_json, "
                       "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                       (insight["insight_id"], c["key"], insight["severity"], insight["title"], insight["detail"],
                        insight["source"], json.dumps(insight["suggestion"]), _now(), _now()))
        emit(self.event_sink, "insight", None, **insight)
        return insight

    def _resolve(self, key: str) -> None:
        self._raised.pop(key, None)
        with self.store.connect() as db:
            rows = db.execute("SELECT insight_id, title FROM insights WHERE insight_key=? AND status='open'",
                              (key,)).fetchall()
            db.execute("UPDATE insights SET status='resolved', updated_at=? WHERE insight_key=? AND status='open'",
                       (_now(), key))
        for row in rows:
            emit(self.event_sink, "insight", None, insight_id=row["insight_id"], title=row["title"],
                 severity="info", detail="Condition cleared.", source="environment", suggestion=None,
                 status="resolved")

    def insights(self, *, status: str = "open", limit: int = 30) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM insights WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                              (status, max(1, min(limit, 200)))).fetchall()
        return [{"insight_id": r["insight_id"], "severity": r["severity"], "title": r["title"],
                 "detail": r["detail"], "source": r["source"],
                 "suggestion": json.loads(r["suggestion_json"]) if r["suggestion_json"] else None,
                 "status": r["status"], "created_at": r["created_at"]} for r in rows]

    def dismiss(self, insight_id: str) -> bool:
        with self.store.connect() as db:
            cur = db.execute("UPDATE insights SET status='dismissed', updated_at=? WHERE insight_id=? AND status='open'",
                             (_now(), insight_id))
        return cur.rowcount > 0

    # --------------------------------------------------------------- context
    def context(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self.samples)
            apps = list(self.app_history)
        if not samples:
            return {"observing": self._thread is not None and self._thread.is_alive(), "samples": 0}
        last = samples[-1]
        window = samples[-10:]
        return {
            "observing": self._thread is not None and self._thread.is_alive(),
            "latest": last,
            "trend_last_samples": {
                "cpu_percent_avg": round(sum(s.get("cpu_percent", 0) for s in window) / len(window), 1),
                "memory_percent_avg": round(sum(s.get("memory_percent", 0) for s in window) / len(window), 1),
            },
            "recent_foreground_apps": [{"since": at, "app": app} for at, app in apps[-8:]],
            "open_insights": self.insights(limit=5),
            "sample_interval_seconds": self.interval,
        }


def register_environment_tools(registry, monitor: EnvironmentMonitor) -> None:
    from senti.tools.registry import ToolDefinition
    registry.register(ToolDefinition(
        name="senti_get_environment_context",
        description="Read SENTI's live picture of the PC: current CPU/memory/disk/battery/network, recent trend, recently used apps (names only) and open proactive insights.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        risk="read_only",
        handler=lambda _args: {"summary": "Returned the current environment context.",
                               **monitor.context(), "verified": True},
    ))
