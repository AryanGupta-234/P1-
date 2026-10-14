"""Fault-isolated, read-only observer runtime with cooperative pause/resume."""
from __future__ import annotations

import time
from pathlib import Path

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import WindowsProvider, host_id
from aie.store import EventStore

# Full service/task/app/network enumeration is intentionally less frequent than
# process/resource sampling to bound host overhead on 16 GB laptops.
STATE_SNAPSHOT_INTERVAL = 30.0


def _health_event(event_type: str, collector: str, data: dict) -> AIEEvent:
    return AIEEvent(
        host_id=host_id(), source="aie.runtime", event_type=event_type,
        entity=EntityRef(type="collector", name=collector),
        data=data, sensitivity="internal",
    )


def observe(
    duration: int,
    interval: float,
    db_path: Path,
    jsonl_path: Path | None = None,
    pause_file: Path | None = None,
) -> int:
    """Observe for *active* duration; presence of pause_file suspends sampling."""
    if duration < 1:
        raise ValueError("duration must be at least 1 second")
    if not 0.5 <= interval <= 60:
        raise ValueError("interval must be between 0.5 and 60 seconds")

    provider = WindowsProvider()
    store = EventStore(db_path)
    deadline = time.monotonic() + duration
    total = 0
    failures = {"process_snapshot": 0, "state_snapshot": 0}
    paused = False
    pause_started = 0.0
    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    output = jsonl_path.open("a", encoding="utf-8") if jsonl_path else None

    def persist(events: list[AIEEvent]) -> None:
        nonlocal total
        if not events:
            return
        total += store.append_many(events)
        if output:
            for event in events:
                output.write(event.model_dump_json() + "\\n")
            output.flush()

    def recovered(collector: str) -> list[AIEEvent]:
        previous = failures[collector]
        failures[collector] = 0
        if previous:
            return [_health_event(
                "observer.collector_recovered", collector,
                {"previous_consecutive_failures": previous},
            )]
        return []

    def failed(collector: str, exc: Exception) -> AIEEvent:
        failures[collector] += 1
        # Exclude exception messages: they may contain paths or host-specific data.
        return _health_event(
            "observer.collector_error", collector,
            {"exception_type": type(exc).__name__,
             "consecutive_failures": failures[collector]},
        )

    first_sample = True
    next_state_sample = 0.0
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            should_pause = bool(pause_file and pause_file.exists())
            if should_pause:
                if not paused:
                    paused = True
                    pause_started = now
                    persist([_health_event("observer.paused", "runtime", {})])
                time.sleep(interval)
                continue
            if paused:
                paused = False
                deadline += max(0.0, now - pause_started)
                persist([_health_event("observer.resumed", "runtime", {})])

            try:
                events = list(provider.collect_snapshot(include_host=first_sample))
                first_sample = False
                persist(events)
                persist(recovered("process_snapshot"))
            except Exception as exc:
                persist([failed("process_snapshot", exc)])

            now = time.monotonic()
            if now >= next_state_sample:
                try:
                    persist(list(provider.collect_state_deltas()))
                    persist(recovered("state_snapshot"))
                except Exception as exc:
                    persist([failed("state_snapshot", exc)])
                next_state_sample = now + STATE_SNAPSHOT_INTERVAL

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
    finally:
        if output:
            output.close()
    return total
