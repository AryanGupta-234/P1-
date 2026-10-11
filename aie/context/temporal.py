"""Rule-driven temporal evidence correlation without causal inference."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aie.contracts import AIEEvent


@dataclass(frozen=True, slots=True)
class CorrelationRule:
    name: str
    anchor_event_type: str
    related_event_types: frozenset[str]
    max_gap_seconds: float = 30.0
    same_host_only: bool = True

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 80:
            raise ValueError("rule name must be 1-80 characters")
        if not self.anchor_event_type or len(self.anchor_event_type) > 100:
            raise ValueError("anchor event type must be 1-100 characters")
        if not self.related_event_types:
            raise ValueError("related_event_types cannot be empty")
        if not 0.1 <= self.max_gap_seconds <= 3600:
            raise ValueError("max_gap_seconds must be between 0.1 and 3600 seconds")


@dataclass(frozen=True, slots=True)
class CorrelatedEvidence:
    rule_name: str
    anchor_event_id: str
    related_event_ids: tuple[str, ...]
    host_id: str
    time_span_seconds: float
    observed_event_types: tuple[str, ...]


def correlate_events(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    rules: list[CorrelationRule] | tuple[CorrelationRule, ...],
    *,
    now: datetime | None = None,
    max_input_age_seconds: float = 86_400,
    max_results: int = 500,
) -> tuple[CorrelatedEvidence, ...]:
    """Return evidence groups matched by explicit temporal/type rules.

    The result does not state that related events caused one another and does not infer
    user intent. Same-host matching is the default; cross-host matching must be explicit.
    """
    if not 1 <= max_input_age_seconds <= 604_800:
        raise ValueError("max_input_age_seconds must be between 1 second and 7 days")
    if not 1 <= max_results <= 5000:
        raise ValueError("max_results must be between 1 and 5000")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)

    accepted: list[AIEEvent] = []
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen or event.timestamp.tzinfo is None:
            continue
        timestamp = event.timestamp.astimezone(timezone.utc)
        age = (current - timestamp).total_seconds()
        if age < 0 or age > max_input_age_seconds:
            continue
        accepted.append(event)
        seen.add(event.event_id)

    accepted.sort(key=lambda item: (item.timestamp.astimezone(timezone.utc), item.event_id))
    output: list[CorrelatedEvidence] = []

    for rule in rules:
        anchors = [event for event in accepted if event.event_type == rule.anchor_event_type]
        for anchor in anchors:
            anchor_ts = anchor.timestamp.astimezone(timezone.utc)
            related: list[AIEEvent] = []
            for event in accepted:
                if event.event_id == anchor.event_id:
                    continue
                if event.event_type not in rule.related_event_types:
                    continue
                if rule.same_host_only and event.host_id != anchor.host_id:
                    continue
                delta = abs((event.timestamp.astimezone(timezone.utc) - anchor_ts).total_seconds())
                if delta <= rule.max_gap_seconds:
                    related.append(event)

            if not related:
                continue
            combined = [anchor, *related]
            timestamps = [item.timestamp.astimezone(timezone.utc) for item in combined]
            span = max(timestamps) - min(timestamps)
            output.append(
                CorrelatedEvidence(
                    rule_name=rule.name,
                    anchor_event_id=anchor.event_id,
                    related_event_ids=tuple(item.event_id for item in related),
                    host_id=anchor.host_id,
                    time_span_seconds=round(span.total_seconds(), 6),
                    observed_event_types=tuple(
                        dict.fromkeys(item.event_type for item in combined)
                    ),
                )
            )
            if len(output) >= max_results:
                return tuple(output)

    return tuple(output)
