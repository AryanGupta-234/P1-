"""Process-start intelligence using bounded, explainable metadata heuristics.

This engine reports suspicious context; it never kills, suspends, quarantines, or blocks a
process. Signature state is deliberately not guessed when Windows has not verified it.
"""
from __future__ import annotations

import os
import time
from collections import deque
from typing import Any

from . import core
from . import safeguard

SHELL_PARENTS = frozenset({
    "powershell.exe", "pwsh.exe", "cmd.exe", "wscript.exe", "cscript.exe",
    "mshta.exe", "rundll32.exe", "regsvr32.exe", "installutil.exe", "wmic.exe",
    "msiexec.exe", "forfiles.exe",
})
TRUSTED_ROOTS = ("\\windows\\", "\\program files\\", "\\program files (x86)\\")
USER_WRITABLE_MARKERS = (
    "\\appdata\\local\\temp\\", "\\windows\\temp\\", "\\downloads\\",
    "\\desktop\\", "\\users\\public\\",
)
_RECENT: deque[dict[str, Any]] = deque(maxlen=120)
_COUNTS = {"observed": 0, "review": 0}


def assess_process(row: dict[str, Any]) -> dict[str, Any]:
    """Score contextual anomalies, never label a process as malware."""
    name = str(row.get("name") or "<unknown>").casefold()
    exe = str(row.get("exe") or "")
    path = os.path.normcase(os.path.abspath(exe)).casefold() if exe else ""
    parent = str(row.get("parent_name") or "").casefold()
    score = 0
    reasons: list[str] = []
    if safeguard.is_protected_process(name, exe):
        return {"score": 0, "level": "protected", "reasons": ["protected operating-system or Riot/Vanguard identity"], "signature": "not queried"}
    if not path:
        score += 12
        reasons.append("executable path unavailable")
    else:
        lower_path = path.replace("/", "\\")
        if any(marker in lower_path for marker in USER_WRITABLE_MARKERS):
            score += 28
            reasons.append("image launched from a user-writable or temporary location")
        elif not any(root in lower_path for root in TRUSTED_ROOTS):
            score += 8
            reasons.append("image is outside standard Windows/Program Files locations")
        if os.path.basename(path) != name:
            score += 18
            reasons.append("process name differs from executable basename")
        if row.get("path_state") in ("missing", "file_missing_or_unmounted", "inaccessible", "access_denied"):
            score += 15
            reasons.append("executable path is missing or inaccessible")
    if parent in SHELL_PARENTS:
        score += 24
        reasons.append(f"started by script/command host {parent}")
    if row.get("session_id") == 0 and row.get("visible_windows"):
        score += 8
        reasons.append("service-session process reports visible-window metadata")
    score = min(100, score)
    level = "high" if score >= 60 else "review" if score >= 35 else "normal"
    return {
        "score": score,
        "level": level,
        "reasons": reasons or ["no high-signal process-start anomaly detected"],
        "signature": "not queried; no unsigned/signed claim is made",
        "assessment_limit": "heuristic context only; this is not antivirus or a malware verdict",
    }


def observe_process_start(row: dict[str, Any]) -> dict[str, Any]:
    """Persist one process-start observation after the collector's warm-up baseline."""
    assessment = assess_process(row)
    record = {
        "ts": time.time(),
        "pid": int(row.get("pid") or 0),
        "create_time": float(row.get("create_time") or 0),
        "name": str(row.get("name") or "<unknown>")[:180],
        "exe": str(row.get("exe") or "")[:1000],
        "parent_name": str(row.get("parent_name") or "")[:120],
        "parent_pid": row.get("parent_pid"),
        "session_id": row.get("session_id"),
        "assessment": assessment,
    }
    _RECENT.appendleft(record)
    _COUNTS["observed"] += 1
    if assessment["level"] in ("review", "high"):
        _COUNTS["review"] += 1
        core.log(
            "process-security",
            f"process start needs review: {record['name']} · score {assessment['score']}/100",
            "warn" if assessment["level"] == "review" else "error",
            pid=record["pid"], executable=record["exe"], parent=record["parent_name"],
            reasons=assessment["reasons"],
        )
        core.insight(
            "high" if assessment["level"] == "high" else "warn",
            f"process-start-review-{record['pid']}-{int(record['create_time'])}",
            f"Review new process: {record['name']}",
            "; ".join(assessment["reasons"]) + ". This is a heuristic alert, not a malware verdict.",
            record["exe"],
        )
    else:
        core.log(
            "process-watch",
            f"new process observed: {record['name']} (pid {record['pid']})",
            "info",
            executable=record["exe"], parent=record["parent_name"], pid=record["pid"],
            assessment=assessment["level"],
        )
    return record


def snapshot(limit: int = 40) -> dict[str, Any]:
    return {
        "observed": _COUNTS["observed"],
        "review_candidates": _COUNTS["review"],
        "recent": list(_RECENT)[:max(1, min(120, int(limit)))],
        "policy": "metadata-only; no process termination, quarantine, injection, memory inspection, or driver installation",
    }


def reset_session() -> None:
    _RECENT.clear()
    _COUNTS.update(observed=0, review=0)
