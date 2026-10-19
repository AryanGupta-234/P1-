"""Bounded Windows ETW process start/stop observer.

ETW is opt-in because kernel tracing can require an elevated token and has a
different privilege/performance profile from user-mode polling. Only process
lifecycle metadata is retained: PID, parent PID, image basename, event kind and
a bounded process key. Command lines, executable paths and arbitrary event
payloads are never stored.
"""
from __future__ import annotations

import ctypes
import os
import queue
import re
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id

_PROCESS_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class ETWEventLike(Protocol):
    event_id: int
    provider_name: str

    def to_dict(self) -> dict[str, Any]: ...


class KernelSessionLike(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def next_event_timeout(self, timeout_ms: int) -> ETWEventLike | None: ...


def _is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _safe_int(properties: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = properties.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str):
            try:
                parsed = int(value, 0)
            except ValueError:
                continue
            if parsed >= 0:
                return parsed
    return None


def _safe_image_name(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    basename = value.replace("/", "\\").rsplit("\\", 1)[-1].strip()
    return basename if _PROCESS_NAME.fullmatch(basename) else "unknown"


class WindowsETWProcessProvider:
    """Consume Microsoft kernel process ETW events into normalized AIE events."""

    name = "windows.etw.process"

    def __init__(
        self,
        *,
        session_factory: Callable[[], KernelSessionLike] | None = None,
        max_queue: int = 512,
        max_events_per_poll: int = 100,
        timeout_ms: int = 20,
        require_admin: bool = True,
    ) -> None:
        if os.name != "nt":
            raise OSError("Windows ETW observation requires native Windows.")
        if require_admin and not _is_windows_admin():
            raise PermissionError(
                "Kernel ETW process observation requires an elevated Windows token."
            )
        if not 32 <= max_queue <= 8192:
            raise ValueError("max_queue must be between 32 and 8192")
        if not 1 <= max_events_per_poll <= 1000:
            raise ValueError("max_events_per_poll must be between 1 and 1000")
        if not 1 <= timeout_ms <= 1000:
            raise ValueError("timeout_ms must be between 1 and 1000 ms")

        self.max_events_per_poll = max_events_per_poll
        self.timeout_ms = timeout_ms
        self._session_factory = session_factory or self._default_session_factory
        self._queue: queue.Queue[ETWEventLike] = queue.Queue(maxsize=max_queue)
        self._session: KernelSessionLike | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._queue_drops = 0
        self._provider_error: str | None = None
        self._running = False
        self._start()

    @staticmethod
    def _default_session_factory() -> KernelSessionLike:
        try:
            # pyetwkit 3.2.0 exports KernelSession and its explicit enable_* methods.
            # Do not use the older PyKernelFlags/PyKernelSession names.
            from pyetwkit._core import KernelSession
        except ImportError as exc:
            raise RuntimeError(
                "Install ETW support with: python -m pip install -e '.[windows]'"
            ) from exc
        session = KernelSession()
        session.enable_process()
        return session

    def _start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._provider_error = None
            session = self._session_factory()
            session.start()
            self._session = session
            self._running = True
            self._worker = threading.Thread(
                target=self._consume,
                name="aie-etw-process",
                daemon=True,
            )
            self._worker.start()

    def _consume(self) -> None:
        while not self._stop.is_set():
            session = self._session
            if session is None:
                return
            try:
                event = session.next_event_timeout(self.timeout_ms)
            except Exception as exc:
                with self._lock:
                    self._provider_error = type(exc).__name__
                return
            if event is None:
                continue
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                with self._lock:
                    self._queue_drops += 1

    def pause(self) -> None:
        self.close()

    def resume(self) -> None:
        self._start()

    def collect_snapshot(self) -> list[AIEEvent]:
        events: list[AIEEvent] = []
        for _ in range(self.max_events_per_poll):
            try:
                raw = self._queue.get_nowait()
            except queue.Empty:
                break
            normalized = self._normalize(raw)
            if normalized is not None:
                events.append(normalized)

        with self._lock:
            error = self._provider_error
            self._provider_error = None
            drops = self._queue_drops
            self._queue_drops = 0

        if error is not None:
            events.append(self._health_event("provider_error", {"error_type": error}))
        if drops:
            events.append(
                self._health_event(
                    "queue_drop",
                    {"dropped_events": drops, "loss_kind": "consumer_queue_drop"},
                )
            )
        return events

    def _health_event(self, suffix: str, data: dict[str, Any]) -> AIEEvent:
        return AIEEvent(
            timestamp=datetime.now(timezone.utc),
            host_id=host_id(),
            source=self.name,
            event_type=f"process.etw_health.{suffix}",
            entity=EntityRef(type="etw_session", name="kernel_process"),
            data=data,
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        )

    @staticmethod
    def _normalize(raw: ETWEventLike) -> AIEEvent | None:
        try:
            event_id = int(raw.event_id)
            payload = raw.to_dict()
            properties = payload.get("properties", {})
            if not isinstance(properties, dict):
                properties = {}
            provider_name = str(getattr(raw, "provider_name", ""))[:128]
        except (AttributeError, TypeError, ValueError):
            return None

        if event_id not in {1, 2, 3, 4}:
            return None

        pid = _safe_int(properties, "ProcessId", "ProcessID", "ProcessID32")
        if pid is None or pid == 0:
            return None
        parent_pid = _safe_int(properties, "ParentId", "ParentID", "ParentProcessId")
        image_name = _safe_image_name(
            properties.get("ImageFileName")
            or properties.get("ImageName")
            or properties.get("ProcessName")
        )
        process_key = _safe_int(
            properties,
            "UniqueProcessKey",
            "ProcessKey",
            "ProcessGuid",
        )
        kind = "start" if event_id in {1, 3} else "stop"
        stable_id = f"{pid}:{process_key}" if process_key is not None else f"{pid}"

        return AIEEvent(
            timestamp=datetime.now(timezone.utc),
            host_id=host_id(),
            source=WindowsETWProcessProvider.name,
            event_type=f"process.etw_{kind}",
            entity=EntityRef(
                type="process",
                name=image_name,
                stable_id=stable_id,
            ),
            data={
                "pid": pid,
                "parent_pid": parent_pid,
                "process_name": image_name,
                "lifecycle": kind,
                "etw_event_id": event_id,
                "provider_name": provider_name,
                "process_key_present": process_key is not None,
                "command_line_collected": False,
                "executable_path_collected": False,
            },
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        )

    def close(self) -> None:
        with self._lock:
            session = self._session
            worker = self._worker
            self._session = None
            self._worker = None
            if not self._running and session is None:
                return
            self._running = False
            self._stop.set()

        if session is not None:
            try:
                session.stop()
            except Exception:
                pass
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.5)

    def __enter__(self) -> "WindowsETWProcessProvider":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
