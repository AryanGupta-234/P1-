"""Privacy-safe observer health telemetry and event-loss accounting.

Health records describe the observation runtime itself. They never include exception
messages, command lines, window titles, control text, or provider payloads.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from aie.contracts import AIEEvent, EntityRef


@dataclass
class _ProviderStats:
    samples_attempted: int = 0
    samples_succeeded: int = 0
    events_emitted: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    event_loss: int = 0
    total_latency_ms: float = 0.0
    last_latency_ms: float | None = None
    last_error_type: str | None = None
    last_error_at: str | None = None


class ObserverHealthTracker:
    """Track bounded provider health without retaining exception details."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started = clock()
        self._providers: OrderedDict[str, _ProviderStats] = OrderedDict()

    def record_sample(
        self,
        provider_name: str,
        *,
        elapsed_seconds: float,
        emitted_events: int,
        error_type: str | None = None,
    ) -> None:
        if not provider_name or emitted_events < 0:
            raise ValueError("provider_name must be non-empty and emitted_events must be non-negative")
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")

        stats = self._providers.setdefault(provider_name, _ProviderStats())
        stats.samples_attempted += 1
        stats.events_emitted += emitted_events
        stats.total_latency_ms += elapsed_seconds * 1000.0
        stats.last_latency_ms = elapsed_seconds * 1000.0

        if error_type is None:
            stats.samples_succeeded += 1
            stats.consecutive_errors = 0
            stats.last_error_type = None
            stats.last_error_at = None
            return

        stats.errors += 1
        stats.consecutive_errors += 1
        stats.last_error_type = error_type
        stats.last_error_at = datetime.now(timezone.utc).isoformat()

    def record_event_loss(self, provider_name: str, count: int = 1) -> None:
        if not provider_name or count < 0:
            raise ValueError("provider_name must be non-empty and count must be non-negative")
        stats = self._providers.setdefault(provider_name, _ProviderStats())
        stats.event_loss += count

    def snapshot(self) -> dict[str, object]:
        runtime_seconds = max(0.0, self._clock() - self._started)
        providers: dict[str, object] = {}
        for name, stats in self._providers.items():
            average = (
                stats.total_latency_ms / stats.samples_attempted
                if stats.samples_attempted
                else None
            )
            providers[name] = {
                "state": "degraded" if stats.consecutive_errors else "ok",
                "samples_attempted": stats.samples_attempted,
                "samples_succeeded": stats.samples_succeeded,
                "events_emitted": stats.events_emitted,
                "errors": stats.errors,
                "consecutive_errors": stats.consecutive_errors,
                "event_loss": stats.event_loss,
                "average_latency_ms": None if average is None else round(average, 2),
                "last_latency_ms": (
                    None if stats.last_latency_ms is None
                    else round(stats.last_latency_ms, 2)
                ),
                "last_error_type": stats.last_error_type,
                "last_error_at": stats.last_error_at,
            }
        return {
            "runtime_seconds": round(runtime_seconds, 3),
            "providers": providers,
        }

    def to_event(self, host_id: str) -> AIEEvent:
        snapshot = self.snapshot()
        return AIEEvent(
            host_id=host_id,
            source="aie.observer",
            event_type="observer.health",
            entity=EntityRef(type="observer", name="runtime"),
            data=snapshot,
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="derived",
        )
