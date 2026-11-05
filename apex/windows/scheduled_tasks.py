"""Task Scheduler COM inspection and exact-path task run/enable operations."""
from __future__ import annotations
import os

PROTECTED_PREFIXES = ("\\Microsoft\\Windows\\",)

def _service():
    if os.name != "nt":
        raise OSError("Task Scheduler provider requires Windows")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Task Scheduler operations") from exc
    service = win32com.client.Dispatch("Schedule.Service")
    service.Connect()
    return service

def list_tasks(limit: int = 300) -> dict:
    if isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    service = _service()
    rows = []
    def visit(folder, depth: int = 0) -> None:
        if depth > 8 or len(rows) >= limit:
            return
        for task in folder.GetTasks(1):
            if len(rows) >= limit:
                return
            try:
                rows.append({"name": str(task.Name)[:180], "path": str(task.Path)[:500],
                    "enabled": bool(task.Enabled), "state": int(task.State),
                    "last_run_time": str(task.LastRunTime), "next_run_time": str(task.NextRunTime),
                    "last_task_result": int(task.LastTaskResult)})
            except Exception:
                continue
        for child in folder.GetFolders(0):
            visit(child, depth + 1)
            if len(rows) >= limit:
                return
    visit(service.GetFolder("\\"))
    return {"tasks": rows, "count": len(rows), "source": "Windows Task Scheduler COM API"}

def _target(path: str):
    if not isinstance(path, str) or not path.startswith("\\") or ".." in path.split("\\"):
        raise ValueError("task path must be an exact absolute Task Scheduler path")
    if any(path.casefold().startswith(prefix.casefold()) for prefix in PROTECTED_PREFIXES):
        raise PermissionError("Microsoft Windows scheduled tasks are protected by default")
    service = _service()
    folder_path, _, name = path.rpartition("\\")
    if not name:
        raise ValueError("task path must include a task name")
    return service.GetFolder(folder_path or "\\").GetTask(name)

def run_task(path: str) -> dict:
    task = _target(path)
    running = task.Run(None)
    return {"summary": f"Requested Task Scheduler run for {path}.", "path": path,
            "state": int(task.State), "instance_id": str(running.InstanceGuid), "verified": False,
            "verification": "Run was accepted; completion and last result require later inspection."}

def set_task_enabled(path: str, enabled: bool) -> dict:
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    task = _target(path)
    task.Enabled = enabled
    observed = bool(task.Enabled)
    if observed is not enabled:
        raise RuntimeError("Task Scheduler enabled-state verification failed")
    return {"summary": f"Task {path} is {'enabled' if enabled else 'disabled'}.",
            "path": path, "enabled": observed, "verified": True}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32com.client
        return True
    except ImportError:
        return False
