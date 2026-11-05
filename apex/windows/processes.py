"""Bounded read-only Windows process inventory and detail."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import psutil


def process_details(pid: int) -> dict:
    if os.name != "nt":
        raise OSError("process inspection requires Windows")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("pid must be a positive integer")
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            created = proc.create_time()
            name = proc.name() or ""
            memory = proc.memory_info()
            cpu = proc.cpu_times()
            try:
                owner = proc.username()
            except psutil.AccessDenied:
                owner = None
            try:
                parent = proc.ppid()
            except psutil.Error:
                parent = None
            try:
                thread_count = proc.num_threads()
            except psutil.Error:
                thread_count = None
            try:
                open_files_count = len(proc.open_files())
            except psutil.Error:
                open_files_count = None
        return {"pid": pid, "name": name, "created_at_epoch": created, "owner": owner,
                "parent_pid": parent, "thread_count": thread_count,
                "memory_rss_bytes": memory.rss, "memory_vms_bytes": memory.vms,
                "user_cpu_seconds": cpu.user, "system_cpu_seconds": cpu.system,
                "open_file_count": open_files_count, "source": "psutil/Windows",
                "observed_at": datetime.now(timezone.utc).isoformat()}
    except psutil.NoSuchProcess as exc:
        raise LookupError("process no longer exists") from exc
    except psutil.AccessDenied as exc:
        raise PermissionError("Windows denied access to process metadata") from exc
