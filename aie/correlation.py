"""Conservative cross-source correlation for process lifecycle evidence."""
from __future__ import annotations

import math
from pathlib import PureWindowsPath
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from aie.contracts import AIEEvent, EntityRef

_ETW_START = "process.started_etw"
_SNAPSHOT_STARTS = {"process.started_observed", "process.replaced_observed"}


def correlate_process_starts(
    events: Iterable[AIEEvent], *, tolerance_seconds: float = 5.0
) -> list[AIEEvent]:
    """Confirm ETW process starts against snapshot starts using PID, image and create time.

    Stop events are intentionally excluded: a stop record containing only a PID cannot
    safely distinguish a prior process instance from a later reuse of that PID.
    """
    if not math.isfinite(tolerance_seconds) or tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be finite and non-negative")

    materialized = list(events)
    snapshots: dict[tuple[str, int, str], list[AIEEvent]] = {}
    for event in materialized:
        if event.event_type not in _SNAPSHOT_STARTS:
            continue
        pid = _pid(event)
        create_time = _create_time(event)
        image = _image(event)
        if pid is None or create_time is None or image is None:
            continue
        snapshots.setdefault((event.host_id, pid, image), []).append(event)

    derived: list[AIEEvent] = []
    for etw in materialized:
        if etw.event_type != _ETW_START:
            continue
        pid = _pid(etw)
        image = _image(etw)
        if pid is None or image is None:
            continue
        candidates = snapshots.get((etw.host_id, pid, image), [])
        if not candidates:
            continue

        matches: list[tuple[float, AIEEvent]] = []
        for snapshot in candidates:
            create_time = _create_time(snapshot)
            if create_time is None:
                continue
            delta = abs(etw.timestamp.timestamp() - create_time)
            if delta <= tolerance_seconds:
                matches.append((delta, snapshot))
        if not matches:
            continue

        delta, snapshot = min(
            matches, key=lambda item: (item[0], item[1].event_id)
        )
        evidence_ids = sorted((etw.event_id, snapshot.event_id))
        correlation_id = str(uuid5(
            NAMESPACE_URL, "aie-process-start|" + "|".join(evidence_ids)
        ))
        derived.append(AIEEvent(
            event_id=correlation_id,
            timestamp=max(etw.timestamp, snapshot.timestamp),
            host_id=etw.host_id,
            source="aie.correlation.process",
            event_type="process.start_confirmed_by_etw",
            entity=EntityRef(
                type="process",
                name=snapshot.entity.name,
                stable_id=str(pid),
            ),
            data={
                "pid": pid,
                "process_create_time": _create_time(snapshot),
                "etw_event_id": etw.event_id,
                "snapshot_event_id": snapshot.event_id,
                "create_time_delta_seconds": round(delta, 6),
            },
            sensitivity="internal",
            confidence=0.99,
            correlation_id=correlation_id,
            evidence_kind="derived",
        ))
    return derived


def _pid(event: AIEEvent) -> int | None:
    value = event.data.get("pid")
    if value is None:
        value = event.entity.stable_id
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid >= 0 else None


def _image(event: AIEEvent) -> str | None:
    value = event.data.get("image_name") or event.entity.name
    if not isinstance(value, str) or not value.strip():
        return None
    name = PureWindowsPath(value).name.casefold()
    return name or None


def _create_time(event: AIEEvent) -> float | None:
    value = event.data.get("create_time")
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return result
