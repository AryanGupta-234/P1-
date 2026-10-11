"""Read-only Windows inventory and best-effort process lifecycle observations."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import platform
import subprocess
from collections.abc import Iterator

import psutil

from aie.contracts import AIEEvent, EntityRef
from aie.providers.base import ObserverProvider


def host_id() -> str:
    # Stable local pseudonymous identifier; no serial numbers or account identifiers.
    raw = f"{platform.node()}|{platform.system()}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:20]


class WindowsProvider(ObserverProvider):
    """Windows user-mode provider. It never starts, stops or modifies system resources."""

    name = "windows.user_mode"

    def __init__(self):
        if os.name != "nt":
            raise OSError("AIE currently supports native Windows only.")
        self._known: dict[int, tuple[str, float | None]] = {}
        self._initialized = False

    def collect_snapshot(self, *, include_host: bool = True) -> Iterator[AIEEvent]:
        if include_host:
            yield AIEEvent(
                host_id=host_id(), source=self.name, event_type="host.snapshot",
                entity=EntityRef(type="host", name=platform.node()),
                data={
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "cpu_logical": psutil.cpu_count(logical=True),
                    "cpu_physical": psutil.cpu_count(logical=False),
                    "memory_total_bytes": psutil.virtual_memory().total,
                },
                sensitivity="internal",
            )

        memory = psutil.virtual_memory()
        system_drive = os.environ.get("SystemDrive", "C:") + os.sep
        try:
            disk = psutil.disk_usage(system_drive)
            disk_payload = {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "percent_used": disk.percent,
            }
        except OSError:
            disk_payload = None
        yield AIEEvent(
            host_id=host_id(), source=self.name, event_type="host.resources",
            entity=EntityRef(type="host", name=platform.node()),
            data={
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_total_bytes": memory.total,
                "memory_available_bytes": memory.available,
                "memory_percent_used": memory.percent,
                "disk_system_volume": disk_payload,
            },
            sensitivity="internal",
        )

        current: dict[int, tuple[str, float | None]] = {}
        for proc in psutil.process_iter(attrs=["pid", "name", "create_time"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                name = str(info.get("name") or "unknown")
                created = info.get("create_time")
                current[pid] = (name, float(created) if created else None)
            except (
                psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess,
                TypeError, ValueError,
            ):
                continue

        # The first sample is a baseline, not a fabricated list of process-start events.
        if not self._initialized:
            self._known = current
            self._initialized = True
            yield AIEEvent(
                host_id=host_id(), source=self.name, event_type="process.baseline",
                entity=EntityRef(type="host", name=platform.node()),
                data={"process_count": len(current)},
                sensitivity="internal",
            )
            return

        for pid, (name, created) in current.items():
            previous = self._known.get(pid)
            if previous is None:
                event_type = "process.started_observed"
            elif previous[1] != created:
                event_type = "process.replaced_observed"  # PID reuse
            else:
                continue
            yield AIEEvent(
                host_id=host_id(), source=self.name, event_type=event_type,
                entity=EntityRef(type="process", name=name, stable_id=str(pid)),
                data={"pid": pid, "create_time": created},
                sensitivity="internal", confidence=0.85, evidence_kind="derived",
            )

        for pid, (name, created) in self._known.items():
            if pid not in current:
                yield AIEEvent(
                    host_id=host_id(), source=self.name,
                    event_type="process.stopped_observed",
                    entity=EntityRef(type="process", name=name, stable_id=str(pid)),
                    data={"pid": pid, "create_time": created},
                    sensitivity="internal", confidence=0.85, evidence_kind="derived",
                )
        self._known = current

    @staticmethod
    def _installed_applications() -> list[dict]:
        """Read uninstall registry metadata; never reads uninstall commands or secrets."""
        import winreg

        roots = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
             winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
             winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0)),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
             winreg.KEY_READ),
        ]
        apps: dict[tuple[str, str], dict] = {}
        for hive, registry_path, access in roots:
            try:
                parent = winreg.OpenKey(hive, registry_path, 0, access)
            except OSError:
                continue
            with parent:
                index = 0
                while True:
                    try:
                        child_name = winreg.EnumKey(parent, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        child = winreg.OpenKey(parent, child_name, 0, access)
                        with child:
                            display_name = winreg.QueryValueEx(child, "DisplayName")[0]
                            if not isinstance(display_name, str) or not display_name.strip():
                                continue
                            try:
                                system_component = winreg.QueryValueEx(child, "SystemComponent")[0]
                            except OSError:
                                system_component = 0
                            if system_component == 1:
                                continue

                            def query(name: str):
                                try:
                                    return winreg.QueryValueEx(child, name)[0]
                                except OSError:
                                    return None

                            item = {
                                "name": display_name.strip(),
                                "version": query("DisplayVersion"),
                                "publisher": query("Publisher"),
                                "install_location": query("InstallLocation"),
                            }
                            key = (item["name"].casefold(), str(item["version"] or ""))
                            apps[key] = item
                    except OSError:
                        continue
        return sorted(apps.values(), key=lambda item: item["name"].casefold())

    @staticmethod
    def _services() -> list[dict]:
        results = []
        try:
            iterator = psutil.win_service_iter()
            for service in iterator:
                try:
                    info = service.as_dict()
                    results.append({
                        "name": info.get("name"),
                        "display_name": info.get("display_name"),
                        "status": info.get("status"),
                        "start_type": info.get("start_type"),
                    })
                except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                    continue
        except (AttributeError, NotImplementedError, OSError):
            return []
        return sorted(results, key=lambda item: (item["name"] or "").casefold())

    @staticmethod
    def _network_interfaces() -> list[dict]:
        # Deliberately excludes IP addresses, MAC addresses, gateways and DNS details.
        stats = psutil.net_if_stats()
        return [
            {
                "name": name,
                "is_up": info.isup,
                "speed_mbps": info.speed,
                "mtu": info.mtu,
                "duplex": int(info.duplex or 0),
            }
            for name, info in sorted(stats.items())
        ]

    @staticmethod
    def _scheduled_tasks() -> dict:
        """Read task name/status metadata via schtasks; does not export task XML or run tasks."""
        try:
            result = subprocess.run(
                ["schtasks.exe", "/query", "/fo", "CSV", "/nh"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=20, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "reason": type(exc).__name__, "tasks": []}
        if result.returncode != 0:
            return {"available": False, "reason": "schtasks_query_failed", "tasks": []}
        tasks = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if not row or not row[0].strip():
                continue
            tasks.append({
                "task_name": row[0].strip(),
                "next_run": row[1].strip() if len(row) > 1 else None,
                "status": row[2].strip() if len(row) > 2 else None,
            })
        return {"available": True, "tasks": tasks}

    def inventory(self) -> dict:
        processes = []
        for proc in psutil.process_iter(attrs=["pid", "name", "create_time"]):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return {
            "host": platform.node(),
            "platform": platform.platform(),
            "cpu_logical": psutil.cpu_count(logical=True),
            "cpu_physical": psutil.cpu_count(logical=False),
            "memory": psutil.virtual_memory()._asdict(),
            "process_count": len(processes),
            "processes": processes,
            "applications": self._installed_applications(),
            "services": self._services(),
            "network_interfaces": self._network_interfaces(),
            "scheduled_tasks": self._scheduled_tasks(),
        }
