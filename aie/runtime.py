"""AIE read-only environment observation runtime."""
from __future__ import annotations

import time
from pathlib import Path

from aie.providers.foreground import WindowsForegroundProvider
from aie.providers.network import WindowsNetworkProvider
from aie.providers.windows import WindowsProvider
from aie.store import EventStore


def observe(
    duration: int,
    interval: float,
    db_path: Path,
    jsonl_path: Path | None = None,
    *,
    include_network: bool = True,
    network_interval: float = 15.0,
    include_foreground: bool = True,
    include_window_titles: bool = False,
) -> int:
    """Persist read-only system, foreground-app and bounded network observations."""
    if duration < 1:
        raise ValueError("duration must be at least 1 second")
    if not 0.5 <= interval <= 60:
        raise ValueError("interval must be between 0.5 and 60 seconds")
    if not 5.0 <= network_interval <= 300:
        raise ValueError("network_interval must be between 5 and 300 seconds")
    if include_window_titles and not include_foreground:
        raise ValueError("window titles require foreground observation to be enabled")

    provider = WindowsProvider()
    network_provider = WindowsNetworkProvider() if include_network else None
    foreground_provider = (
        WindowsForegroundProvider(include_window_titles=include_window_titles)
        if include_foreground
        else None
    )
    store = EventStore(db_path)
    deadline = time.monotonic() + duration
    next_network = 0.0
    total = 0

    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    output = jsonl_path.open("a", encoding="utf-8") if jsonl_path else None
    first_sample = True
    try:
        while time.monotonic() < deadline:
            events = list(provider.collect_snapshot(include_host=first_sample))
            first_sample = False

            if foreground_provider is not None:
                events.extend(foreground_provider.collect_snapshot())

            now = time.monotonic()
            if network_provider is not None and now >= next_network:
                events.extend(network_provider.collect_snapshot())
                next_network = now + network_interval

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
