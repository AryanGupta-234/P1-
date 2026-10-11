"""Fail-closed execution controls for registered policy-mediated adapters.

Creating or removing the enable/kill-switch markers performs no OS action by itself.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class ExecutionBlocked(RuntimeError):
    """Raised when mutation is not permitted by the global execution gate."""


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    max_seconds: float = 10.0
    max_output_bytes: int = 1_048_576
    max_processes: int = 1
    network_allowed: bool = False
    filesystem_write_allowed: bool = False
    privileged: bool = False

    def __post_init__(self) -> None:
        if not 0.1 <= self.max_seconds <= 300.0:
            raise ValueError("max_seconds must be between 0.1 and 300")
        if not 1_024 <= self.max_output_bytes <= 8 * 1024 * 1024:
            raise ValueError("max_output_bytes must be between 1024 and 8 MiB")
        if not 1 <= self.max_processes <= 16:
            raise ValueError("max_processes must be between 1 and 16")
        if self.privileged:
            raise ValueError("privileged execution is not supported by the safety contract")


@dataclass(frozen=True, slots=True)
class ExecutionGateStatus:
    enabled: bool
    kill_switch_active: bool

    @property
    def mutation_allowed(self) -> bool:
        return self.enabled and not self.kill_switch_active


def _is_regular_marker(path: Path) -> bool:
    """Accept only a regular file; symlinks and other file types fail closed."""
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _marker_present(path: Path) -> bool:
    """Count symlinks (including broken links) and non-file objects as present."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        # An unreadable kill-switch path must be treated as active.
        return True
    return True


def _create_marker_exclusively(path: Path) -> None:
    """Create a zero-byte marker without following an existing symlink."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if not _is_regular_marker(path):
            raise ExecutionBlocked("execution marker exists but is not a regular file")
        return
    except OSError as exc:
        raise ExecutionBlocked(
            f"unable to create execution marker ({type(exc).__name__})"
        ) from exc
    else:
        os.close(descriptor)


class ExecutionControl:
    """Fail-closed global control surface for explicitly enabled adapters."""

    def __init__(
        self,
        *,
        enabled_path: Path,
        kill_switch_path: Path,
    ) -> None:
        self.enabled_path = enabled_path
        self.kill_switch_path = kill_switch_path

    def status(self) -> ExecutionGateStatus:
        return ExecutionGateStatus(
            enabled=_is_regular_marker(self.enabled_path),
            kill_switch_active=_marker_present(self.kill_switch_path),
        )

    def require_mutation_allowed(self) -> None:
        status = self.status()
        if not status.enabled:
            raise ExecutionBlocked(
                "Real execution is disabled by default; explicit execution enablement is required."
            )
        if status.kill_switch_active:
            raise ExecutionBlocked(
                "The global execution kill switch is active; no mutation is permitted."
            )

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.enabled_path.parent.mkdir(parents=True, exist_ok=True)
            _create_marker_exclusively(self.enabled_path)
            return
        try:
            self.enabled_path.unlink()
        except FileNotFoundError:
            pass

    def set_kill_switch(self, active: bool) -> None:
        if active:
            self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
            _create_marker_exclusively(self.kill_switch_path)
            return
        try:
            self.kill_switch_path.unlink()
        except FileNotFoundError:
            pass
