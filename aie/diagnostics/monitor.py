"""Live, deduplicated observation-to-diagnosis monitor.

This component creates recommendation events only. It does not execute remediation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from aie.context.video import build_video_observation_context
from aie.contracts import AIEEvent, EntityRef
from aie.diagnostics.video_buffering import diagnose_video_buffering
from aie.store import EventStore


class VideoDiagnosticMonitor:
    """Convert fresh correlated playback evidence into deduplicated diagnostic events."""

    def __init__(
        self,
        store: EventStore,
        *,
        max_age_seconds: float = 45.0,
        alert_cooldown_seconds: float = 120.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1.0 <= max_age_seconds <= 300.0:
            raise ValueError("max_age_seconds must be between 1 and 300")
        if not 0.0 <= alert_cooldown_seconds <= 3600.0:
            raise ValueError("alert_cooldown_seconds must be between 0 and 3600")
        self.store = store
        self.max_age_seconds = max_age_seconds
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._active_causes: set[str] = set()
        self._last_alert_at: dict[str, datetime] = {}
        self._load_recent_alerts()

    def _load_recent_alerts(self) -> None:
        """Avoid replaying a just-issued alert when the observer process restarts."""
        now = self.clock()
        cutoff = now - timedelta(seconds=self.alert_cooldown_seconds)
        for event in self.store.recent(1000):
            if event.event_type != "diagnostic.video_finding":
                continue
            cause = event.data.get("cause")
            if not isinstance(cause, str):
                continue
            if event.timestamp.tzinfo is None:
                continue
            if event.timestamp >= cutoff:
                previous = self._last_alert_at.get(cause)
                if previous is None or event.timestamp > previous:
                    self._last_alert_at[cause] = event.timestamp

    def poll(self) -> list[AIEEvent]:
        """Return new finding events; caller persists them and presents notifications."""
        now = self.clock()
        # Refresh persisted cooldowns on every poll so independent browser native-host
        # processes observe findings created by their siblings.
        self._load_recent_alerts()
        events = self.store.recent(1000)
        context = build_video_observation_context(
            events,
            now=now,
            max_age_seconds=self.max_age_seconds,
        )
        if context is None:
            self._active_causes.clear()
            return []

        report = diagnose_video_buffering(context.metrics)
        current_causes = {finding.cause for finding in report.findings}
        new_events: list[AIEEvent] = []

        for finding in report.findings:
            if finding.cause in self._active_causes:
                continue
            last_alert = self._last_alert_at.get(finding.cause)
            if (
                last_alert is not None
                and self.alert_cooldown_seconds > 0
                and (now - last_alert).total_seconds() < self.alert_cooldown_seconds
            ):
                continue

            event = AIEEvent(
                timestamp=now,
                host_id=context.host_id,
                source="aie.diagnostics.video",
                event_type="diagnostic.video_finding",
                entity=EntityRef(type="diagnostic", name=finding.cause),
                data={
                    "cause": finding.cause,
                    "severity": finding.severity,
                    "confidence": finding.confidence,
                    "recommendation": finding.recommendation,
                    "evidence": list(finding.evidence),
                    "evidence_event_ids": list(context.evidence_event_ids),
                    "disclaimer": report.disclaimer,
                    "action_executed": False,
                },
                sensitivity="internal",
                confidence=finding.confidence,
                correlation_id=context.evidence_event_ids[0],
                evidence_kind="derived",
            )
            new_events.append(event)
            self._last_alert_at[finding.cause] = now

        self._active_causes = current_causes
        return new_events
