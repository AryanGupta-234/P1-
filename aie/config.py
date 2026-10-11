"""Local AIE paths."""
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
