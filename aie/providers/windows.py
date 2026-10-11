"""Read-only Windows host/process observations.

Lifecycle events inferred from snapshots are best-effort; ETW is planned for higher fidelity.
"""
from __future__ import annotations
import hashlib
import os
import platform
from collections.abc import Iterator
import psutil
from aie.contracts import AIEEvent, EntityRef
from aie.providers.base import ObserverProvider


def host_id() -> str:
    raw = f"{platform.node()}|{platform.system()}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:20]


class WindowsProvider(ObserverProvider):
    name = "windows.user_mode"

    def __init__(self):
        if os.name != "nt":
            raise OSError("AIE currently supports native Windows only.")
        self._known: dict[int, tuple[str, float | None]] = {}

    def collect_snapshot(self) -> Iterator[AIEEvent]:
        yield AIEEvent(
            host_id=host_id(), source=self.name, event_type="host.snapshot",
            entity=EntityRef(type="host", name=platform.node()),
            data={"platform": platform.platform(), "python": platform.python_version(),
                  "cpu_count": psutil.cpu_count(), "memory_total": psutil.virtual_memory().total},
            sensitivity="internal")
        current: dict[int, tuple[str, float | None]] = {}
        for proc in psutil.process_iter(attrs=["pid", "name", "create_time"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                name = str(info.get("name") or "unknown")
                created = info.get("create_time")
                current[pid] = (name, float(created) if created else None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess,
                    TypeError, ValueError):
                continue
        for pid, (name, created) in current.items():
            if pid not in self._known:
                yield AIEEvent(
                    host_id=host_id(), source=self.name,
                    event_type="process.started_observed",
                    entity=EntityRef(type="process", name=name, stable_id=str(pid)),
                    data={"pid": pid, "create_time": created}, sensitivity="internal",
                    confidence=0.85, evidence_kind="derived")
        for pid, (name, created) in self._known.items():
            if pid not in current:
                yield AIEEvent(
                    host_id=host_id(), source=self.name,
                    event_type="process.stopped_observed",
                    entity=EntityRef(type="process", name=name, stable_id=str(pid)),
                    data={"pid": pid, "create_time": created}, sensitivity="internal",
                    confidence=0.85, evidence_kind="derived")
        self._known = current

    def inventory(self) -> dict:
        processes = []
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return {"host": platform.node(), "platform": platform.platform(),
                "cpu_count": psutil.cpu_count(), "memory": psutil.virtual_memory()._asdict(),
                "process_count": len(processes), "processes": processes}
