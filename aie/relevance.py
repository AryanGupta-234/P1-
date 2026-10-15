"""Deterministic relevance ranking for observed environment state.

Scores express retrieval priority, not truth, risk, or calibrated confidence.
No model inference or external data is used.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from aie.state_model import EnvironmentProjection


def rank_environment_state(
    projection: EnvironmentProjection,
    *,
    now: datetime | None = None,
    limit: int = 50,
    half_life_hours: float = 24.0,
) -> list[dict[str, Any]]:
    """Rank state records using transparent recency and operational-salience features."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not math.isfinite(half_life_hours) or half_life_hours <= 0:
        raise ValueError("half_life_hours must be finite and positive")

    ranked: list[dict[str, Any]] = []

    def add(kind: str, key: str, name: str, status: str, observed_at: datetime,
            evidence_ids: list[str], *, etw_confirmed: bool = False,
            collection: str | None = None, truncated: bool = False) -> None:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return
        age_hours = max(0.0, (now - observed_at).total_seconds() / 3600.0)
        recency = math.exp(-math.log(2) * age_hours / half_life_hours)
        score = 0.55 * recency
        reasons = [f"recency={recency:.3f} (half-life {half_life_hours:g}h)"]
        if status in {"running", "present"}:
            score += 0.25
            reasons.append("currently observed as active/present")
        elif status in {"stopped", "removed", "replaced"}:
            reasons.append(f"terminal state: {status}")
        if etw_confirmed:
            score += 0.15
            reasons.append("process start independently confirmed by ETW")
        if truncated:
            reasons.append("older evidence references were truncated")
        score = min(1.0, score)
        ranked.append({
            "kind": kind,
            "key": key,
            "name": name,
            "status": status,
            "score": round(score, 6),
            "last_observed": observed_at.astimezone(timezone.utc).isoformat(),
            "evidence_ids": list(evidence_ids[-64:]),
            "evidence_truncated": bool(truncated),
            "reasons": reasons,
            **({"collection": collection} if collection is not None else {}),
        })

    for item in projection.processes.values():
        add(
            "process", f"{item.host_id}:{item.pid}:{item.create_time:.6f}",
            item.image, item.status, item.last_observed, item.evidence_ids,
            etw_confirmed=item.etw_confirmed,
            truncated=getattr(item, "evidence_truncated", False),
        )
    for item in projection.entities.values():
        add(
            "entity", f"{item.host_id}:{item.collection}:{item.identity}",
            item.name, item.status, item.last_observed, item.evidence_ids,
            collection=item.collection,
            truncated=getattr(item, "evidence_truncated", False),
        )
    ranked.sort(key=lambda row: (-row["score"], row["kind"], row["key"]))
    return ranked[:limit]
