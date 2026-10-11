"""Read-only observer runtime with a baseline followed by change detection."""
from __future__ import annotations

import time
from pathlib import Path

from aie.providers.windows import WindowsProvider
from aie.store import EventStore


def observe(
    duration: int,
    interval: float,
    db_path: Path,
    jsonl_path: Path | None = None,
) -> int:
    if duration < 1:
        raise ValueError("duration must be at least 1 second")
    if not 0.5 <= interval <= 60:
        raise ValueError("interval must be between 0.5 and 60 seconds")

    provider = WindowsProvider()
    store = EventStore(db_path)
    deadline = time.monotonic() + duration
    total = 0
    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    output = jsonl_path.open("a", encoding="utf-8") if jsonl_path else None
    first_sample = True
    try:
        while time.monotonic() < deadline:
            events = list(provider.collect_snapshot(include_host=first_sample))
            first_sample = False
            total += store.append_many(events)
            if output:
                for event in events:
                    output.write(event.model_dump_json() + "\n")
                output.flush()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
    finally:
        if output:
            output.close()
    return total
