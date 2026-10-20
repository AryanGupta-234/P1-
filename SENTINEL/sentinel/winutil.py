"""Windows command discovery and bounded process helpers.

Prefer explicit System32 paths over PATH lookup: Scheduled Tasks and SYSTEM or
restricted service contexts frequently have a shorter PATH than an interactive shell.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _system_candidates(name: str) -> list[str]:
    if os.name != "nt":
        return []
    root = os.environ.get("SystemRoot", r"C:\Windows")
    system32 = os.path.join(root, "System32")
    sysnative = os.path.join(root, "Sysnative")
    rel = {
        "powershell": [r"WindowsPowerShell\v1.0\powershell.exe"],
        "powershell.exe": [r"WindowsPowerShell\v1.0\powershell.exe"],
        "typeperf": ["typeperf.exe"], "typeperf.exe": ["typeperf.exe"],
        "wpr": ["wpr.exe"], "wpr.exe": ["wpr.exe"],
        "wevtutil": ["wevtutil.exe"], "wevtutil.exe": ["wevtutil.exe"],
        "logman": ["logman.exe"], "logman.exe": ["logman.exe"],
        "powercfg": ["powercfg.exe"], "powercfg.exe": ["powercfg.exe"],
        "sc": ["sc.exe"], "sc.exe": ["sc.exe"],
        "tasklist": ["tasklist.exe"], "tasklist.exe": ["tasklist.exe"],
        "ping": ["ping.exe"], "ping.exe": ["ping.exe"],
        "ipconfig": ["ipconfig.exe"], "ipconfig.exe": ["ipconfig.exe"],
    }.get(name.lower(), [name])
    paths: list[str] = []
    # Sysnative bypasses WOW64 redirection when SENTINEL is launched by 32-bit Python.
    for base in (sysnative, system32):
        paths.extend(os.path.join(base, part) for part in rel)
    return paths


def resolve_command(name: str) -> str | None:
    """Resolve an executable using PATH and known Windows system locations."""
    if not name:
        return None
    # For well-known OS utilities, prefer the Windows-owned System32/Sysnative
    # copy over PATH. PATH can be user-controlled and is frequently truncated in
    # scheduled tasks; accepting an earlier powershell.exe/sc.exe is both brittle
    # and a potential executable-search-order hijack. Unknown vendor tools may
    # still be resolved from PATH after known system locations are checked.
    for candidate in _system_candidates(name):
        if os.path.isfile(candidate):
            return candidate
    return shutil.which(name)


def run_command(
    command: str | Sequence[str], *, timeout: float = 15,
    check: bool = False, input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a discovered command without a shell and with bounded execution time."""
    parts = [command] if isinstance(command, str) else list(command)
    if not parts:
        raise ValueError("command must not be empty")
    executable = resolve_command(str(parts[0]))
    if not executable:
        raise FileNotFoundError(f"executable not found: {parts[0]}")
    parts[0] = executable
    return subprocess.run(
        parts, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=check, creationflags=_NO_WINDOW, input=input_text,
    )


def powershell_executable() -> str | None:
    return resolve_command("powershell.exe") or resolve_command("pwsh.exe")


def powershell(script: str, *, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    """Execute a PowerShell script using a fully resolved executable."""
    exe = powershell_executable()
    if not exe:
        raise FileNotFoundError("Windows PowerShell or PowerShell 7 was not found")
    return subprocess.run(
        [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_NO_WINDOW,
    )