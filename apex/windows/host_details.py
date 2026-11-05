"""Additional read-only Windows inventory using Python APIs and Windows COM/WMI."""
from __future__ import annotations
import os
import re
from datetime import datetime, timezone

def _windows() -> None:
    if os.name != "nt":
        raise OSError("Windows inventory provider is available only on Windows")

def network_summary() -> dict:
    _windows()
    import psutil
    addresses, stats = psutil.net_if_addrs(), psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    interfaces = []
    for name, addrs in addresses.items():
        stat, io = stats.get(name), counters.get(name)
        interfaces.append({"name": name, "is_up": bool(stat.isup) if stat else None,
            "speed_mbps": stat.speed if stat else None, "mtu": stat.mtu if stat else None,
            "addresses": [{"family": str(a.family), "address": a.address, "netmask": a.netmask,
                           "broadcast": a.broadcast} for a in addrs[:8]],
            "bytes_sent": io.bytes_sent if io else None, "bytes_received": io.bytes_recv if io else None,
            "packets_sent": io.packets_sent if io else None, "packets_received": io.packets_recv if io else None})
    return {"interfaces": interfaces, "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "Windows interfaces via psutil", "dns_and_routes": "not yet exposed by this provider"}

def storage_summary() -> dict:
    _windows()
    import psutil
    volumes = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            continue
        volumes.append({"device": partition.device, "mountpoint": partition.mountpoint,
            "filesystem": partition.fstype, "total_bytes": usage.total, "used_bytes": usage.used,
            "free_bytes": usage.free, "percent_used": usage.percent})
    io = psutil.disk_io_counters(perdisk=True) or {}
    return {"volumes": volumes, "disk_io": {name: {"read_bytes": item.read_bytes,
            "write_bytes": item.write_bytes, "read_time_ms": item.read_time, "write_time_ms": item.write_time}
            for name, item in list(io.items())[:64]}, "source": "Windows storage via psutil"}

def startup_entries(limit: int = 200) -> dict:
    _windows()
    import winreg
    if isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    locations = [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU Run"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU RunOnce"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM RunOnce")]
    rows = []
    for hive, key_path, source in locations:
        try:
            with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    try:
                        name, value, _kind = winreg.EnumValue(key, i)
                        match = re.match(r'^"([^"]+)"|^([^\s]+)', str(value).strip())
                        target = (match.group(1) or match.group(2)) if match else ""
                        rows.append({"name": str(name)[:180], "target_executable": target[:400],
                                     "arguments_collected": False, "source": source})
                    except OSError:
                        continue
                    if len(rows) >= limit:
                        break
        except OSError:
            continue
        if len(rows) >= limit:
            break
    return {"entries": rows, "count": len(rows), "source": "Windows Run/RunOnce registry metadata"}

def pnp_devices(limit: int = 300) -> dict:
    _windows()
    if isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for PnP inventory") from exc
    locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    service = locator.ConnectServer(".", "root\\cimv2")
    collection = service.ExecQuery("SELECT Name, DeviceID, Status, ConfigManagerErrorCode FROM Win32_PnPEntity")
    rows = []
    for item in collection:
        rows.append({"name": str(item.Name or "")[:240], "device_id": str(item.DeviceID or "")[:500],
                     "status": str(item.Status or "unknown"),
                     "problem_code": int(item.ConfigManagerErrorCode) if item.ConfigManagerErrorCode is not None else None})
        if len(rows) >= limit:
            break
    return {"devices": rows, "count": len(rows), "source": "WMI Win32_PnPEntity"}

def recent_events(log_name: str = "System", limit: int = 50) -> dict:
    _windows()
    if log_name not in {"System", "Application"}:
        raise ValueError("only System and Application event logs are allowlisted")
    if isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    import win32evtlog
    handle = win32evtlog.OpenEventLog(None, log_name)
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    rows = []
    try:
        while len(rows) < limit:
            batch = win32evtlog.ReadEventLog(handle, flags, 0)
            if not batch:
                break
            for event in batch:
                rows.append({"event_id": int(event.EventID & 0xFFFF), "source": str(event.SourceName)[:180],
                    "event_type": int(event.EventType), "generated_at": event.TimeGenerated.isoformat(),
                    "record_number": int(event.RecordNumber), "computer": str(event.ComputerName)[:180]})
                if len(rows) >= limit:
                    break
    finally:
        win32evtlog.CloseEventLog(handle)
    return {"log": log_name, "events": rows, "count": len(rows),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "Windows Event Log metadata; event messages are not collected"}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import psutil
        return True
    except ImportError:
        return False
