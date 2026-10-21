"""Process-start intelligence using bounded, explainable metadata heuristics.

This engine reports suspicious context; it never kills, suspends, quarantines, or blocks a
process. Signature state is deliberately not guessed when Windows has not verified it.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
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


def _verified_process_file(pid: int, create_time: float, executable: str) -> tuple[str, os.stat_result]:
    """Revalidate a process instance by PID, creation time and executable path."""
    if pid <= 4 or create_time <= 0:
        raise ValueError("invalid process identity")
    supplied = os.path.normcase(os.path.abspath(executable))
    if not supplied or not os.path.isabs(supplied):
        raise ValueError("an absolute executable path is required")
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name() or ""
            actual_create = float(proc.create_time())
            actual_exe = os.path.normcase(os.path.abspath(proc.exe() or ""))
        if safeguard.is_protected_process(name, actual_exe):
            raise PermissionError("protected Riot/Vanguard or Windows process; inspection denied")
        if abs(actual_create - create_time) > 0.02 or actual_exe != supplied:
            raise ValueError("process identity changed; refresh the process list and retry")
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        raise ValueError("process has already exited") from None
    except psutil.AccessDenied:
        raise PermissionError("Windows denied access to process metadata; no privilege escalation attempted") from None

    if not os.path.isfile(actual_exe):
        raise ValueError("the executable file is unavailable")
    stat = os.stat(actual_exe)
    if not os.path.isfile(actual_exe):
        raise ValueError("the executable file changed or disappeared")
    return actual_exe, stat


def inspect_process(pid: int, create_time: float, executable: str, operation: str) -> dict[str, Any]:
    """Inspect a reviewed process image on demand; never reads process memory or command lines."""
    if not core.IS_WIN:
        raise RuntimeError("process file inspection is Windows-only")
    operation = str(operation or "").casefold()
    if operation not in {"signature", "sha256", "open_location"}:
        raise ValueError("operation must be signature, sha256 or open_location")

    guard = safeguard.snapshot()
    if not guard["process_detection_complete"]:
        raise PermissionError("process observer unavailable; inspection blocked fail-closed")
    if guard["valorant_active"]:
        raise PermissionError("VALORANT is active; SENTINEL forensic subprocess operations are paused")
    exe, before = _verified_process_file(int(pid), float(create_time), str(executable))
    result: dict[str, Any] = {
        "operation": operation,
        "pid": int(pid),
        "executable": exe,
        "file_size": int(before.st_size),
        "last_modified": float(before.st_mtime),
        "read_only": True,
    }

    if operation == "signature":
        from .winutil import powershell
        escaped = exe.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'; "
            f"$sig=Get-AuthenticodeSignature -LiteralPath '{escaped}'; "
            "[ordered]@{status=[string]$sig.Status; "
            "status_message=[string]$sig.StatusMessage; "
            "signer=if($sig.SignerCertificate){[string]$sig.SignerCertificate.Subject}else{''}; "
            "thumbprint=if($sig.SignerCertificate){[string]$sig.SignerCertificate.Thumbprint}else{''}} "
            "| ConvertTo-Json -Compress"
        )
        completed = powershell(script, timeout=20)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Authenticode query failed")[:240])
        try:
            signature = json.loads((completed.stdout or "").strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError("PowerShell returned an invalid signature result") from exc
        # File may have been replaced during the signature query. Revalidate identity and mtime.
        _after_path, after = _verified_process_file(int(pid), float(create_time), exe)
        if after.st_size != before.st_size or after.st_mtime != before.st_mtime:
            raise RuntimeError("executable file changed during signature verification; result discarded")
        result["signature"] = signature
        result["interpretation"] = (
            "Authenticode status is a trust/signature indicator, not a malware verdict. "
            "NotSigned does not alone mean malicious; Valid does not alone guarantee safe behavior."
        )
        return result

    if operation == "sha256":
        max_bytes = 2 * 1024 * 1024 * 1024
        if before.st_size > max_bytes:
            raise ValueError("hashing is limited to files up to 2 GiB to bound CPU and disk use")
        digest = hashlib.sha256()
        with open(exe, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        _after_path, after = _verified_process_file(int(pid), float(create_time), exe)
        if after.st_size != before.st_size or after.st_mtime != before.st_mtime:
            raise RuntimeError("executable file changed while hashing; result discarded")
        result.update({"algorithm": "SHA-256", "digest": digest.hexdigest(),
                       "bytes_hashed": int(after.st_size),
                       "interpretation": "File identity fingerprint only; this hash is not a malware verdict."})
        return result

    from .winutil import resolve_command
    explorer = resolve_command("explorer.exe")
    if not explorer:
        raise RuntimeError("Windows Explorer executable was not found")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([explorer, f"/select,{exe}"], close_fds=True, creationflags=flags)
    result["opened"] = True
    result["interpretation"] = "Opened the executable's folder in Explorer; no file contents were changed."
    return result
