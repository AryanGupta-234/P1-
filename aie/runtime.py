"""AIE read-only environment observation runtime."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from aie.contracts import AIEEvent
from aie.diagnostics.monitor import VideoDiagnosticMonitor
from aie.health import ObserverHealthTracker

from aie.providers.foreground import WindowsForegroundProvider
from aie.providers.eventlog import WindowsEventLogProvider
from aie.providers.network import WindowsNetworkProvider
from aie.providers.process_resources import WindowsProcessResourceProvider
from aie.providers.windows import WindowsProvider, host_id
from aie.providers.uia import WindowsUIATreeProvider
from aie.config import observer_is_paused
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
    foreground_sample_interval: float = 5.0,
    include_video_diagnostics: bool = True,
    diagnostic_max_age_seconds: float = 45.0,
    diagnostic_cooldown_seconds: float = 120.0,
    on_diagnostic: Callable[[AIEEvent], None] | None = None,
    include_ui_tree: bool = False,
    ui_tree_app_names: set[str] | None = None,
    ui_tree_sample_interval: float = 10.0,
    include_event_logs: bool = False,
    event_log_channels: tuple[str, ...] = ("Application", "System"),
    event_log_interval: float = 30.0,
    event_log_max_records: int = 50,
    include_process_resources: bool = False,
    process_resource_interval: float = 10.0,
    process_resource_max_processes: int = 256,
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
    if not 1.0 <= foreground_sample_interval <= 60.0:
        raise ValueError("foreground_sample_interval must be between 1 and 60 seconds")
    if include_ui_tree and not ui_tree_app_names:
        raise ValueError("UI Automation requires an explicit foreground app allowlist")
    if include_ui_tree and not 2.0 <= ui_tree_sample_interval <= 300.0:
        raise ValueError("ui_tree_sample_interval must be between 2 and 300 seconds")
    if include_event_logs and not 5.0 <= event_log_interval <= 300.0:
        raise ValueError("event_log_interval must be between 5 and 300 seconds")
    if include_event_logs and not 1 <= event_log_max_records <= 200:
        raise ValueError("event_log_max_records must be between 1 and 200")
    if include_process_resources and not 2.0 <= process_resource_interval <= 300.0:
        raise ValueError("process_resource_interval must be between 2 and 300 seconds")
    if include_process_resources and not 1 <= process_resource_max_processes <= 512:
        raise ValueError("process_resource_max_processes must be between 1 and 512")

    provider = WindowsProvider()
    network_provider = WindowsNetworkProvider() if include_network else None
    foreground_provider = (
        WindowsForegroundProvider(
            include_window_titles=include_window_titles,
            resource_sample_interval=foreground_sample_interval,
        )
        if include_foreground
        else None
    )
    process_resource_provider = (
        WindowsProcessResourceProvider(
            max_processes=process_resource_max_processes,
            sample_interval=process_resource_interval,
        )
        if include_process_resources
        else None
    )
    event_log_provider = (
        WindowsEventLogProvider(
            channels=event_log_channels,
            max_records_per_channel=event_log_max_records,
        )
        if include_event_logs
        else None
    )
    uia_provider = (
        WindowsUIATreeProvider(
            allowed_process_names=ui_tree_app_names or set(),
            sample_interval=ui_tree_sample_interval,
        )
        if include_ui_tree
        else None
    )
    store = EventStore(db_path)
    health_tracker = ObserverHealthTracker(host_id=host_id())
    diagnostic_monitor = (
        VideoDiagnosticMonitor(
            store,
            max_age_seconds=diagnostic_max_age_seconds,
            alert_cooldown_seconds=diagnostic_cooldown_seconds,
        )
        if include_video_diagnostics
        else None
    )
    deadline = time.monotonic() + duration
    next_network = 0.0
    next_event_log = 0.0
    next_process_resources = 0.0
    total = 0

    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    output = jsonl_path.open("a", encoding="utf-8") if jsonl_path else None
    first_sample = True
    try:
        while time.monotonic() < deadline:
            if observer_is_paused():
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(interval, remaining))
                continue

            events = health_tracker.collect(
                "windows.user_mode",
                lambda: provider.collect_snapshot(include_host=first_sample),
            )
            first_sample = False

            if foreground_provider is not None:
                events.extend(
                    health_tracker.collect(
                        "windows.foreground", foreground_provider.collect_snapshot
                    )
                )
            if uia_provider is not None:
                events.extend(
                    health_tracker.collect(
                        "windows.uia", uia_provider.collect_snapshot
                    )
                )

            now = time.monotonic()
            if network_provider is not None and now >= next_network:
                events.extend(
                    health_tracker.collect(
                        "windows.network", network_provider.collect_snapshot
                    )
                )
                next_network = now + network_interval
            if event_log_provider is not None and now >= next_event_log:
                events.extend(
                    health_tracker.collect(
                        "windows.eventlog", event_log_provider.collect_snapshot
                    )
                )
                next_event_log = now + event_log_interval
            if process_resource_provider is not None and now >= next_process_resources:
                events.extend(process_resource_provider.collect_snapshot())
                next_process_resources = now + process_resource_interval

            total += store.append_many(events)
            diagnostic_events = (
                diagnostic_monitor.poll()
                if diagnostic_monitor is not None
                else []
            )
            if diagnostic_events:
                total += store.append_many(diagnostic_events)

            if output:
                for event in [*events, *diagnostic_events]:
                    output.write(event.model_dump_json() + "\n")
                output.flush()

            if on_diagnostic is not None:
                for event in diagnostic_events:
                    on_diagnostic(event)

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
    finally:
        summaries = health_tracker.summary_events()
        if summaries:
            total += store.append_many(summaries)
            if output:
                for event in summaries:
                    output.write(event.model_dump_json() + "\n")
                output.flush()
        if output:
            output.close()
    return total
