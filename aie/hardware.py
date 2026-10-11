"""Runtime hardware/resource snapshot for safe local model decisions."""
from __future__ import annotations

import os
import platform

import psutil


def runtime_profile() -> dict:
    memory = psutil.virtual_memory()
    total_gib = memory.total / (1024 ** 3)
    available_gib = memory.available / (1024 ** 3)
    return {
        "platform": platform.platform(),
        "native_windows": os.name == "nt",
        "python": platform.python_version(),
        "cpu_logical": psutil.cpu_count(logical=True),
        "cpu_physical": psutil.cpu_count(logical=False),
        "memory_total_gib": round(total_gib, 2),
        "memory_available_gib": round(available_gib, 2),
        "memory_pressure": "high" if available_gib < 3.0 else (
            "moderate" if available_gib < 7.5 else "normal"
        ),
    }
