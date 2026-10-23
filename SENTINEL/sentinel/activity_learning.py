"""Local online-learning algorithms for foreground activity intelligence.

This module is deliberately UI-independent and network-free. It converts the
agent's locally observed activity into two kinds of evidence:

* semantic task similarity using corpus-weighted term overlap;
* time-aware routine confidence using support, competing outcomes and recency.

The caller owns persistence and policy. No action is executed from this module.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


def _terms(values: Iterable[str]) -> set[str]:
    return {
        str(value).strip().casefold()
        for value in values
        if isinstance(value, str) and len(str(value).strip()) >= 3
    }


def weighted_jaccard(
    left: Iterable[str],
    right: Iterable[str],
    document_frequency: Mapping[str, int] | None = None,
    document_count: int = 0,
) -> float:
    """Return IDF-weighted Jaccard similarity for two observed term sets.

    Common terms contribute less than distinctive terms. This makes dynamic
    task clusters less likely to merge merely because they share generic words.
    """
    a, b = _terms(left), _terms(right)
    if not a or not b:
        return 0.0

    frequencies = document_frequency or {}

    def weight(term: str) -> float:
        df = max(0, int(frequencies.get(term, 0)))
        corpus = max(0, int(document_count))
        return 1.0 + math.log((corpus + 1.0) / (df + 1.0))

    union = a | b
    intersection = a & b
    denominator = sum(weight(term) for term in union)
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, sum(weight(term) for term in intersection) / denominator))


def task_match_score(
    incoming_terms: Iterable[str],
    existing_terms: Iterable[str],
    *,
    document_frequency: Mapping[str, int] | None = None,
    document_count: int = 0,
    last_seen: float = 0.0,
    now: float = 0.0,
) -> float:
    """Score whether a new foreground session belongs to an existing task."""
    similarity = weighted_jaccard(
        incoming_terms, existing_terms, document_frequency, document_count
    )
    if similarity <= 0.0:
        return 0.0

    # Older clusters remain matchable, but recent task context gets a modest
    # preference so an old project does not dominate unrelated new work.
    age_days = max(0.0, (float(now) - float(last_seen)) / 86400.0) if now and last_seen else 0.0
    freshness = 0.82 + 0.18 * math.exp(-age_days / 180.0)
    return max(0.0, min(1.0, similarity * freshness))


def routine_confidence(
    observations: int,
    total_observations: int,
    alternatives: int,
    age_days: float,
    hour_distance: int,
) -> tuple[float, float]:
    """Return (confidence, conditional_probability) for a learned next-app edge.

    Confidence rewards repeated evidence, penalizes competing next applications,
    and decays as the observation becomes stale or the local hour diverges.
    """
    count = max(0, int(observations))
    total = max(count, int(total_observations))
    choices = max(1, int(alternatives))
    if count == 0:
        return 0.0, 0.0

    probability = (count + 0.5) / (total + 0.5 * choices)
    support = 1.0 - math.exp(-count / 3.0)
    selectivity = 0.35 + 0.65 * max(0.0, min(1.0, probability))
    recency = math.exp(-max(0.0, float(age_days)) / 120.0)
    temporal_fit = max(0.70, 1.0 - min(4, max(0, int(hour_distance))) * 0.075)
    confidence = support * selectivity * recency * temporal_fit
    return round(max(0.0, min(0.99, confidence)), 3), round(
        max(0.0, min(1.0, probability)), 3
    )


def hour_distance(left: int, right: int) -> int:
    """Circular clock-hour distance, including windows crossing midnight."""
    a, b = int(left) % 24, int(right) % 24
    delta = abs(a - b)
    return min(delta, 24 - delta)


def rank_task_candidates(
    incoming_terms: Iterable[str],
    candidates: Sequence[Mapping[str, object]],
    *,
    now: float,
) -> list[tuple[float, Mapping[str, object]]]:
    """Score task rows using a shared corpus IDF model and return best-first."""
    parsed: list[tuple[Mapping[str, object], set[str]]] = []
    frequencies: dict[str, int] = {}
    for row in candidates:
        raw = row.get("terms")
        terms = _terms(raw if isinstance(raw, (list, tuple, set)) else [])
        parsed.append((row, terms))
        for term in terms:
            frequencies[term] = frequencies.get(term, 0) + 1

    scored = []
    for row, terms in parsed:
        score = task_match_score(
            incoming_terms,
            terms,
            document_frequency=frequencies,
            document_count=len(parsed),
            last_seen=float(row.get("last_seen") or 0.0),
            now=now,
        )
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (item[0], int(item[1].get("observations") or 0)), reverse=True)
    return scored
