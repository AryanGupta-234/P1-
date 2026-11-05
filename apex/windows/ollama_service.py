"""Discover and optionally start the installed Ollama Windows tray application without a CLI."""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def discover_ollama_app() -> Path | None:
    if os.name != "nt":
        return None
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "Programs" / "Ollama"
        candidates.extend([root / "ollama app.exe", root / "ollama.exe"])
    candidates.extend([
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Ollama" / "ollama app.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Ollama" / "ollama.exe",
    ])
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths\ollama app.exe"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
                try:
                    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                    candidates.insert(0, Path(os.path.expandvars(str(value)).strip('"')))
                except OSError:
                    continue
    except ImportError:
        pass
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            if resolved.is_file() and resolved.suffix.casefold() == ".exe":
                return resolved
        except OSError:
            continue
    return None


def api_ready(base_url: str = "http://127.0.0.1:11434", *, timeout: float = 1.0) -> bool:
    try:
        with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=timeout) as response:
            return response.status == 200
    except (OSError, URLError, TimeoutError):
        return False


def ensure_ollama_available(base_url: str = "http://127.0.0.1:11434", *,
                            auto_start: bool = True, startup_timeout: float = 12.0) -> dict:
    """Connect first; if enabled, launch the installed GUI app directly, never ollama.exe CLI args."""
    if api_ready(base_url):
        return {"status": "connected", "started_by_apex": False, "api": base_url}
    if os.name != "nt":
        return {"status": "unavailable", "started_by_apex": False,
                "reason": "Ollama auto-start integration is Windows-only."}
    if not auto_start:
        return {"status": "unavailable", "started_by_apex": False,
                "reason": "Auto-start is disabled and the Ollama loopback API is not responding."}
    executable = discover_ollama_app()
    if executable is None:
        return {"status": "unavailable", "started_by_apex": False,
                "reason": "The installed Ollama Windows application was not found."}
    try:
        os.startfile(str(executable))
    except OSError as exc:
        return {"status": "unavailable", "started_by_apex": False,
                "reason": f"Windows refused to start the Ollama application ({type(exc).__name__})."}
    deadline = time.monotonic() + max(1.0, min(float(startup_timeout), 30.0))
    while time.monotonic() < deadline:
        if api_ready(base_url, timeout=0.75):
            return {"status": "connected", "started_by_apex": True,
                    "executable": str(executable), "api": base_url}
        time.sleep(0.25)
    return {"status": "unavailable", "started_by_apex": True,
            "executable": str(executable),
            "reason": "Ollama application was launched but its loopback API did not become ready in time."}
