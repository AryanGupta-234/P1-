"""Aggregated user feedback for diagnostic recommendations."""
from __future__ import annotations

from dataclasses import dataclass

from aie.contracts import AIEEvent
from aie.store import EventStore

_VALID_OUTCOMES = {"resolved", "not_resolved", "not_attempted"}


@dataclass(frozen=True, slots=True)
class FeedbackSummary:
    cause: str
    resolved: int
    not_resolved: int
    not_attempted: int

    @property
    def attempted(self) -> int:
        return self.resolved + self.not_resolved

    @property
    def resolution_rate(self) -> float | None:
        """Observed resolution fraction among attempted recommendations only."""
        if self.attempted == 0:
            return None
        return self.resolved / self.attempted


def summarize_feedback(events: list[AIEEvent] | tuple[AIEEvent, ...]) -> list[FeedbackSummary]:
    """Aggregate only explicit user outcomes; ignore malformed and unrelated events."""
    counts: dict[str, dict[str, int]] = {}
    for event in events:
        if event.event_type != "diagnostic.user_feedback":
            continue
        cause = event.data.get("cause")
        outcome = event.data.get("outcome")
        if not isinstance(cause, str) or not cause or outcome not in _VALID_OUTCOMES:
            continue
        bucket = counts.setdefault(
            cause,
            {"resolved": 0, "not_resolved": 0, "not_attempted": 0},
        )
        bucket[outcome] += 1

    summaries = [
        FeedbackSummary(
            cause=cause,
            resolved=values["resolved"],
            not_resolved=values["not_resolved"],
            not_attempted=values["not_attempted"],
        )
        for cause, values in counts.items()
    ]
    return sorted(
        summaries,
        key=lambda item: (item.attempted, item.resolved, item.cause),
        reverse=True,
    )


def load_feedback_summary(store: EventStore, *, limit: int = 1000) -> list[FeedbackSummary]:
    """Summarize recent stored feedback events; this is reporting, not model training."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return summarize_feedback(store.recent(limit))
