"""Freshness weighting and explicit contradiction checks for normalized evidence.

This layer never infers user intent. Freshness is a heuristic ranking factor, not
a calibrated probability. Contradictions are emitted only for narrowly defined
state-like fields when conflicting values are observed for the same fact key
within a very small time window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from aie.contracts import AIEEvent


_STATE_FIELDS = frozenset({"playback_state", "state"})
_ALLOWED_STATE_VALUES = frozenset({
    "playing",
    "waiting",
    "stalled",
    "paused",
    "ended",
    "ok",
    "degraded",
    "active",
    "ended",
})


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    event_id: str
    age_seconds: float
    fresh: bool
    time_weight: float
    effective_confidence: float


@dataclass(frozen=True, slots=True)
class EvidenceContradiction:
    fact_key: tuple[str, str, str]
    event_ids: tuple[str, str]
    values: tuple[str, str]
    time_delta_seconds: float


def assess_evidence(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 120.0,
    half_life_seconds: float = 60.0,
) -> tuple[EvidenceAssessment, ...]:
    """Assign bounded freshness weights without modifying event confidence semantics."""
    if not 0 < max_age_seconds <= 86_400:
        raise ValueError("max_age_seconds must be between 0 and 86400")
    if not 0 < half_life_seconds <= 86_400:
        raise ValueError("half_life_seconds must be between 0 and 86400")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)

    results: list[EvidenceAssessment] = []
    for event in events:
        if event.timestamp.tzinfo is None:
            continue
        age = max(0.0, (current - event.timestamp.astimezone(timezone.utc)).total_seconds())
        fresh = age <= max_age_seconds
        weight = 0.0 if not fresh else 2.0 ** (-age / half_life_seconds)
        effective = round(event.confidence * weight, 6)
        results.append(
            EvidenceAssessment(
                event_id=event.event_id,
                age_seconds=round(age, 3),
                fresh=fresh,
                time_weight=round(weight, 6),
                effective_confidence=effective,
            )
        )
    return tuple(results)


def find_explicit_contradictions(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    window_seconds: float = 1.0,
) -> tuple[EvidenceContradiction, ...]:
    """Find only near-simultaneous conflicts in explicit, allowlisted state fields."""
    if not 0.05 <= window_seconds <= 10.0:
        raise ValueError("window_seconds must be between 0.05 and 10")

    candidates: list[
        tuple[tuple[str, str, str], datetime, str, str]
    ] = []
    for event in events:
        if event.timestamp.tzinfo is None:
            continue
        for field in _STATE_FIELDS:
            raw = event.data.get(field)
            if not isinstance(raw, str):
                continue
            value = raw.strip().casefold()
            if value not in _ALLOWED_STATE_VALUES:
                continue
            entity_key = event.entity.stable_id or event.entity.name
            fact_key = (event.event_type, entity_key, field)
            candidates.append((
                fact_key,
                event.timestamp.astimezone(timezone.utc),
                event.event_id,
                value,
            ))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    contradictions: list[EvidenceContradiction] = []
    for index, current in enumerate(candidates):
        for other in candidates[index + 1:]:
            if other[0] != current[0]:
                if other[0][0] > current[0][0]:
                    break
                continue
            delta = abs((other[1] - current[1]).total_seconds())
            if delta > window_seconds:
                break
            if other[3] == current[3]:
                continue
            first, second = (current, other) if current[1] <= other[1] else (other, current)
            contradictions.append(
                EvidenceContradiction(
                    fact_key=current[0],
                    event_ids=(first[2], second[2]),
                    values=(first[3], second[3]),
                    time_delta_seconds=round(delta, 6),
                )
            )
    return tuple(dict.fromkeys(contradictions))
