"""Sanitized, bounded runtime health telemetry for AIE observer providers."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import time

from aie.contracts import AIEEvent, EntityRef


_FAILURE_SUFFIXES = frozenset({
    "provider_error",
    "provider_timeout",
    "records_lost",
    "sequence_reset",
})


@dataclass(slots=True)
class _ProviderState:
    status: str = "unknown"
    reason_code: str = "not_sampled"
    collections: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    observations: int = 0
    dropped_records: int = 0
    unknown_loss_incidents: int = 0
    last_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    last_error_type: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None


class ObserverHealthTracker:
    """Track provider health without persisting exception messages or stack traces.

    Health transition events are emitted only when a provider changes state.
    A final summary event captures counters at the end of each observer run.
    """

    def __init__(
        self,
        *,
        host_id: str,
        monotonic: Callable[[], float] = time.perf_counter,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.host_id = host_id
        self._monotonic = monotonic
        self._utcnow = utcnow
        self._states: dict[str, _ProviderState] = {}

    def collect(
        self,
        provider: str,
        collector: Callable[[], Iterable[AIEEvent]],
    ) -> list[AIEEvent]:
        """Run one bounded provider pass and append sanitized health transitions."""
        started = self._monotonic()
        try:
            events = list(collector())
        except Exception as exc:
            duration_ms = self._duration_ms(started)
            error_type = type(exc).__name__[:64]
            error_event = self._event(
                "observer.provider_error",
                provider,
                {"provider": provider, "error_type": error_type},
            )
            transition = self._record(
                provider,
                status="degraded",
                reason_code="collector_exception",
                events=1,
                duration_ms=duration_ms,
                error_type=error_type,
            )
            return [error_event, *([transition] if transition else [])]

        duration_ms = self._duration_ms(started)
        failures = [
            event for event in events
            if event.event_type.rsplit(".", 1)[-1] in _FAILURE_SUFFIXES
        ]
        if failures:
            first = failures[0]
            suffix = first.event_type.rsplit(".", 1)[-1]
            error_type = first.data.get("error_type")
            if not isinstance(error_type, str) or not error_type:
                error_type = suffix
            transition = self._record(
                provider,
                status="degraded",
                reason_code=suffix,
                events=len(events),
                duration_ms=duration_ms,
                error_type=error_type[:64],
                dropped_records=sum(
                    value for event in failures
                    if isinstance((value := event.data.get("dropped_records")), int)
                    and value > 0
                ),
                unknown_loss=any(event.event_type.endswith(".sequence_reset") for event in failures),
            )
        else:
            previous = self._states.get(provider)
            if previous is not None and previous.status == "degraded" and not events:
                # Empty polls are not proof of recovery; wait for a positive observation
                # or an explicit provider-recovered event from the sensor.
                transition = self._record(
                    provider,
                    status="degraded",
                    reason_code=previous.reason_code,
                    events=0,
                    duration_ms=duration_ms,
                    error_type=previous.last_error_type,
                    count_failure=False,
                )
            else:
                transition = self._record(
                    provider,
                    status="healthy",
                    reason_code="collection_ok",
                    events=len(events),
                    duration_ms=duration_ms,
                )
        if transition:
            events.append(transition)
        return events

    def summary_events(self) -> list[AIEEvent]:
        """Return one final health summary per provider sampled in this run."""
        return [
            self._event(
                "observer.provider_health_summary",
                provider,
                self._payload(provider, state),
            )
            for provider, state in sorted(self._states.items())
        ]

    def _duration_ms(self, started: float) -> float:
        return round(max(0.0, self._monotonic() - started) * 1000.0, 2)

    def _record(
        self,
        provider: str,
        *,
        status: str,
        reason_code: str,
        events: int,
        duration_ms: float,
        error_type: str | None = None,
        dropped_records: int = 0,
        unknown_loss: bool = False,
        count_failure: bool = True,
    ) -> AIEEvent | None:
        state = self._states.setdefault(provider, _ProviderState())
        previous_status = state.status
        state.collections += 1
        state.observations += max(0, events)
        state.last_duration_ms = duration_ms
        state.max_duration_ms = max(state.max_duration_ms, duration_ms)
        state.reason_code = reason_code
        now = self._utcnow().astimezone(timezone.utc).isoformat()

        if status == "degraded":
            if count_failure:
                state.failures += 1
                state.consecutive_failures += 1
                state.last_failure_at = now
                state.last_error_type = error_type or "ProviderReportedError"
                state.dropped_records += dropped_records
                state.unknown_loss_incidents += int(unknown_loss)
        else:
            state.consecutive_failures = 0
            state.last_success_at = now

        state.status = status
        if previous_status == status:
            return None
        return self._event(
            "observer.provider_health",
            provider,
            self._payload(provider, state),
        )

    @staticmethod
    def _payload(provider: str, state: _ProviderState) -> dict[str, object]:
        return {
            "provider": provider,
            "status": state.status,
            "reason_code": state.reason_code,
            "collections": state.collections,
            "failures": state.failures,
            "consecutive_failures": state.consecutive_failures,
            "observations": state.observations,
            "dropped_records": state.dropped_records,
            "unknown_loss_incidents": state.unknown_loss_incidents,
            "last_duration_ms": state.last_duration_ms,
            "max_duration_ms": state.max_duration_ms,
            "last_error_type": state.last_error_type,
            "last_success_at": state.last_success_at,
            "last_failure_at": state.last_failure_at,
        }

    def _event(
        self,
        event_type: str,
        provider: str,
        data: dict[str, object],
    ) -> AIEEvent:
        return AIEEvent(
            timestamp=self._utcnow().astimezone(timezone.utc),
            host_id=self.host_id,
            source="aie.observer.health",
            event_type=event_type,
            entity=EntityRef(
                type="observer_provider",
                name=provider[:96],
            ),
            data=data,
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        )
