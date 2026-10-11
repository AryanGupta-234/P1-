"""Local AIE paths and observer controls."""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = (Path(base) / "AIE") if base else (Path.home() / ".aie")
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    return data_dir() / "events.sqlite3"


def observer_pause_path() -> Path:
    """Per-user pause marker shared by every running AIE observer instance."""
    return data_dir() / "observer.paused"


def observer_is_paused() -> bool:
    return observer_pause_path().exists()


def set_observer_paused(paused: bool) -> None:
    """Set or clear the global observer pause marker without changing stored data."""
    marker = observer_pause_path()
    if paused:
        marker.touch(exist_ok=True)
        return
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
