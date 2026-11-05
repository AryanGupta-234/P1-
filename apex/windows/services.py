"""Windows Service Control Manager inventory and narrowly allowlisted service actions."""
from __future__ import annotations
import os

PROTECTED_SERVICES = {
    "windefend", "mpssvc", "bfe", "wscsvc", "securityhealthservice", "eventlog", "rpcss",
    "dcomlaunch", "plugplay", "power", "nsi", "dhcp", "dnscache", "lanmanworkstation",
    "lanmanserver", "wlanservice", "vgc", "easyanticheat", "beservice",
}

def list_services(limit: int = 300) -> dict:
    if os.name != "nt":
        raise OSError("service inventory requires Windows")
    if isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    import win32service
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
    rows = []
    try:
        statuses = win32service.EnumServicesStatus(manager, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL)
        for name, display, status in statuses[:limit]:
            rows.append({"name": name, "display_name": display, "service_type": status[0],
                         "state": status[1], "controls_accepted": status[2], "win32_exit_code": status[3]})
    finally:
        win32service.CloseServiceHandle(manager)
    return {"services": rows, "count": len(rows), "source": "Windows Service Control Manager"}

def change_service(name: str, action: str) -> dict:
    if os.name != "nt":
        raise OSError("service control requires Windows")
    if not isinstance(name, str) or not 1 <= len(name) <= 256 or "\\" in name or "/" in name:
        raise ValueError("service name is invalid")
    key = name.casefold()
    if key in PROTECTED_SERVICES or key.startswith(("vg", "easyanticheat", "battleye", "faceit")):
        raise PermissionError("security, networking and anti-cheat services are protected")
    if action not in {"start", "stop"}:
        raise ValueError("action must be start or stop")
    import win32service
    access = win32service.SERVICE_START if action == "start" else win32service.SERVICE_STOP
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        service = win32service.OpenService(manager, name, access | win32service.SERVICE_QUERY_STATUS)
        try:
            status = win32service.QueryServiceStatus(service)
            current = status[1]
            if action == "start" and current == win32service.SERVICE_RUNNING:
                return {"summary": f"Service {name} is already running.", "state": "running", "verified": True}
            if action == "stop" and current == win32service.SERVICE_STOPPED:
                return {"summary": f"Service {name} is already stopped.", "state": "stopped", "verified": True}
            if action == "start":
                win32service.StartService(service, None)
            else:
                win32service.ControlService(service, win32service.SERVICE_CONTROL_STOP)
            return {"summary": f"Sent {action} request to service {name}.", "service": name,
                    "verified": False, "verification": "Check service state with a fresh inventory read."}
        finally:
            win32service.CloseServiceHandle(service)
    finally:
        win32service.CloseServiceHandle(manager)

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32service
        return True
    except ImportError:
        return False
