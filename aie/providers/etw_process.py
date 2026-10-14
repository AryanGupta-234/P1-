"""Opt-in bounded ETW process trace session using Windows' built-in logman.

This module only starts/stops a named user-mode ETW trace session. It never
installs drivers, changes security settings, or reads trace contents.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Callable

KERNEL_PROCESS_PROVIDER = "Microsoft-Windows-Kernel-Process"
KERNEL_PROCESS_GUID = "{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}"
PROCESS_KEYWORD = "0x10"
TRACE_LEVEL_INFORMATION = "4"


class ETWSessionError(RuntimeError):
    """Raised when a bounded ETW trace session cannot be managed."""


class ETWProcessTrace:
    """Context-managed ETW capture with explicit bounds and guaranteed stop attempt."""

    def __init__(
        self,
        output: Path,
        *,
        buffer_size_kb: int = 64,
        min_buffers: int = 16,
        max_buffers: int = 64,
        timeout: float = 15.0,
        max_file_mb: int = 256,
        runner: Callable = subprocess.run,
    ) -> None:
        if os.name != "nt":
            raise OSError("ETW process tracing requires native Windows.")
        if output.suffix.casefold() != ".etl":
            raise ValueError("ETW output must use the .etl extension")
        if not 16 <= buffer_size_kb <= 256:
            raise ValueError("buffer_size_kb must be between 16 and 256")
        if not 4 <= min_buffers <= max_buffers <= 256:
            raise ValueError("buffer counts must satisfy 4 <= min <= max <= 256")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 16 <= max_file_mb <= 2048:
            raise ValueError("max_file_mb must be between 16 and 2048")
        self.output = output
        self.buffer_size_kb = buffer_size_kb
        self.min_buffers = min_buffers
        self.max_buffers = max_buffers
        self.timeout = timeout
        self.max_file_mb = max_file_mb
        self._runner = runner
        self.session_name = f"AIE-Process-{uuid.uuid4().hex[:12]}"
        self._started = False

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        try:
            result = self._runner(
                args, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ETWSessionError(
                f"ETW command failed: {type(exc).__name__}"
            ) from exc
        if result.returncode != 0:
            raise ETWSessionError(f"ETW command returned exit code {result.returncode}")
        return result

    def start(self) -> Path:
        if self._started:
            raise ETWSessionError("ETW session is already running")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.output.exists():
            raise FileExistsError(self.output)
        args = [
            "logman.exe", "start", self.session_name, "-ets",
            "-p", KERNEL_PROCESS_PROVIDER, PROCESS_KEYWORD,
            TRACE_LEVEL_INFORMATION,
            "-o", str(self.output),
            "-bs", str(self.buffer_size_kb),
            "-nb", str(self.min_buffers), str(self.max_buffers),
            "-max", str(self.max_file_mb),
        ]
        self._started = True
        try:
            self._run(args)
        except ETWSessionError as start_error:
            try:
                self._run(["logman.exe", "stop", self.session_name, "-ets"])
            except ETWSessionError as cleanup_error:
                raise ETWSessionError(
                    "ETW start failed and cleanup could not confirm session stop"
                ) from cleanup_error
            self._started = False
            raise start_error
        return self.output

    def stop(self) -> None:
        if not self._started:
            return
        self._run(["logman.exe", "stop", self.session_name, "-ets"])
        self._started = False

    def __enter__(self) -> "ETWProcessTrace":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.stop()
        return False
