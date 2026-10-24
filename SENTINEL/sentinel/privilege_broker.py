"""Per-action Windows elevation launcher.

The normal SENTINEL agent stays unelevated. This module can only launch the
installed agent entry point with one random, database-backed maintenance job ID.
It has no arbitrary command, path, script, or generic process-execution API.
"""
from __future__ import annotations

import ctypes
import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

ADMIN_ACTIONS = frozenset({
    "dns_set", "adapter_restart", "winsock_reset", "driver_install",
    "driver_rollback", "windows_repair", "service_restart", "trim_volume",
    "process_tune",
})
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def is_elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def current_user_binding() -> dict:
    """Bind an approval ticket to the interactive Windows principal and session."""
    if os.name != "nt":
        raise RuntimeError("Interactive Windows identity is unavailable.")
    try:
        import psutil
        principal = str(psutil.Process().username() or getpass.getuser()).strip()
        from .collectors import _session_id
        session_id = _session_id(os.getpid())
    except Exception as exc:
        raise PermissionError("SENTINEL could not verify the current interactive user session.") from exc
    if not principal or session_id in (None, 0):
        raise PermissionError("A signed-in interactive user session is required for administrator actions.")
    return {"principal": principal.casefold(), "session_id": int(session_id)}


def status() -> dict:
    elevated = is_elevated()
    return {
        "platform": "windows" if os.name == "nt" else "unsupported",
        "agent_elevated": elevated,
        "runtime_mode": "elevated_session" if elevated else "standard_user",
        "execution_model": "per_action_uac",
        "admin_action_count": len(ADMIN_ACTIONS),
        "admin_actions": sorted(ADMIN_ACTIONS),
        "arbitrary_command_execution": False,
        "persistent_admin_token": False,
        "approval_required": True,
        "uac_required_for_admin_action": bool(os.name == "nt" and not elevated),
    }


def launch_privileged_job(job_id: str) -> dict:
    """Launch one previously persisted job using the Windows UAC consent UI."""
    if os.name != "nt":
        raise RuntimeError("The Windows privilege broker is unavailable on this platform.")
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ValueError("Privilege broker job identifier is invalid.")
    if is_elevated():
        raise RuntimeError("Agent is already elevated; use the in-process guarded worker.")
    entrypoint = Path(__file__).resolve().parents[1] / "agent.py"
    if not entrypoint.is_file():
        raise RuntimeError("SENTINEL agent entry point was not found.")
    params = subprocess.list2cmdline([str(entrypoint), "--privileged-job", job_id])
    shell = ctypes.windll.shell32.ShellExecuteW
    shell.restype = ctypes.c_void_p
    result = shell(None, "runas", sys.executable, params, str(entrypoint.parent), 0)
    value = int(result or 0)
    if value <= 32:
        if value in (5, 1223):
            raise PermissionError("Windows elevation was declined or access was denied.")
        raise OSError(value, "Windows could not start the approved maintenance helper.")
    return {"started": True, "job_id": job_id, "uac_consent_requested": True,
            "arbitrary_command_execution": False}
