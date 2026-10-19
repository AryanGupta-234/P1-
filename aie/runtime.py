"""AIE read-only environment observation runtime."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from aie.config import observer_is_paused
from aie.contracts import AIEEvent
from aie.diagnostics.monitor import VideoDiagnosticMonitor
from aie.event_bus import EventBus
from aie.observer_health import ObserverHealthTracker
from aie.providers.eventlog import WindowsEventLogProvider
from aie.providers.etw_process import WindowsETWProcessProvider
from aie.providers.foreground import WindowsForegroundProvider
from aie.providers.network import WindowsNetworkProvider
from aie.providers.process_resources import WindowsProcessResourceProvider
from aie.providers.uia import WindowsUIATreeProvider
from aie.providers.windows import WindowsProvider, host_id
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
    include_etw: bool = False,
    etw_max_events_per_poll: int = 100,
    health_interval: float = 30.0,
    stop_file: Path | None = None,
    on_cycle: Callable[[dict[str, object]], None] | None = None,
) -> int:
    """Persist read-only observations and privacy-safe observer health telemetry."""
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
    if include_etw and not 1 <= etw_max_events_per_poll <= 1000:
        raise ValueError("etw_max_events_per_poll must be between 1 and 1000")
    if not 5.0 <= health_interval <= 300.0:
        raise ValueError("health_interval must be between 5 and 300 seconds")

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
    etw_init_error: str | None = None
    etw_provider = None
    if include_etw:
        try:
            etw_provider = WindowsETWProcessProvider(
                max_events_per_poll=etw_max_events_per_poll
            )
        except (OSError, PermissionError, RuntimeError, ValueError) as exc:
            # Optional kernel telemetry must never take down the least-privilege observer.
            etw_init_error = type(exc).__name__
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
    event_bus = EventBus(max_batch_size=2_000)
    event_bus.subscribe("store", store.append_many)
    diagnostic_monitor = (
        VideoDiagnosticMonitor(
            store,
            max_age_seconds=diagnostic_max_age_seconds,
            alert_cooldown_seconds=diagnostic_cooldown_seconds,
        )
        if include_video_diagnostics
        else None
    )
    health = ObserverHealthTracker(clock=time.monotonic)
    if etw_init_error is not None:
        health.record_sample(
            "windows.etw.process",
            elapsed_seconds=0.0,
            emitted_events=0,
            error_type=etw_init_error,
        )
    deadline = time.monotonic() + duration
    next_network = 0.0
    next_event_log = 0.0
    next_process_resources = 0.0
    next_health = 0.0
    total = 0
    etw_paused = False

    cycle_samples: list[dict[str, object]] = []

    def collect(
        provider_name: str,
        collector: Callable[[], list[AIEEvent] | tuple[AIEEvent, ...] | object],
    ) -> list[AIEEvent]:
        started = time.monotonic()
        try:
            collected = list(collector())
        except Exception as exc:  # noqa: BLE001 - observation must degrade instead of stopping the runtime.
            elapsed_ms = max(0.0, time.monotonic() - started) * 1000.0
            health.record_sample(
                provider_name,
                elapsed_seconds=elapsed_ms / 1000.0,
                emitted_events=0,
                error_type=type(exc).__name__,
            )
            cycle_samples.append({
                "provider": provider_name,
                "latency_ms": round(elapsed_ms, 2),
                "events": 0,
                "state": "degraded",
                "error_type": type(exc).__name__,
            })
            return []
        loss_count = 0
        for event in collected:
            if not isinstance(event.data, dict) or not event.data.get("loss_kind"):
                continue
            dropped = event.data.get("dropped_events")
            if isinstance(dropped, int) and dropped >= 0:
                loss_count += dropped
        if loss_count:
            health.record_event_loss(provider_name, loss_count)
        elapsed_ms = max(0.0, time.monotonic() - started) * 1000.0
        health.record_sample(
            provider_name,
            elapsed_seconds=elapsed_ms / 1000.0,
            emitted_events=len(collected),
        )
        cycle_samples.append({
            "provider": provider_name,
            "latency_ms": round(elapsed_ms, 2),
            "events": len(collected),
            "state": "ok",
        })
        return collected

    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    output = jsonl_path.open("a", encoding="utf-8") if jsonl_path else None

    if output:
        def write_jsonl(events: list[AIEEvent] | tuple[AIEEvent, ...]) -> int:
            for event in events:
                output.write(event.model_dump_json() + "\n")
            output.flush()
            return len(events)

        event_bus.subscribe("jsonl", write_jsonl)
    first_sample = True
    try:
        while time.monotonic() < deadline and not (stop_file is not None and stop_file.exists()):
            cycle_samples.clear()
            if observer_is_paused():
                if etw_provider is not None and not etw_paused:
                    etw_provider.pause()
                    etw_paused = True
                remaining = deadline - time.monotonic()
                if on_cycle is not None:
                    try:
                        on_cycle({
                            "status": "paused",
                            "timestamp": time.time(),
                            "provider_health": health.snapshot().get("providers", {}),
                            "events_collected": 0,
                            "providers": [],
                        })
                    except Exception:  # noqa: BLE001 - status observers must not stop collection.
                        pass
                if remaining > 0:
                    time.sleep(min(interval, remaining))
                continue

            if etw_provider is not None and etw_paused:
                etw_provider.resume()
                etw_paused = False

            events = collect(
                provider.name,
                lambda: provider.collect_snapshot(include_host=first_sample),
            )
            first_sample = False

            if foreground_provider is not None:
                events.extend(collect(
                    foreground_provider.name,
                    foreground_provider.collect_snapshot,
                ))
            if uia_provider is not None:
                events.extend(collect(
                    uia_provider.name,
                    uia_provider.collect_snapshot,
                ))

            now = time.monotonic()
            if network_provider is not None and now >= next_network:
                events.extend(collect(
                    network_provider.name,
                    network_provider.collect_snapshot,
                ))
                next_network = now + network_interval
            if event_log_provider is not None and now >= next_event_log:
                events.extend(collect(
                    event_log_provider.name,
                    event_log_provider.collect_snapshot,
                ))
                next_event_log = now + event_log_interval
            if process_resource_provider is not None and now >= next_process_resources:
                events.extend(collect(
                    process_resource_provider.name,
                    process_resource_provider.collect_snapshot,
                ))
                next_process_resources = now + process_resource_interval
            if etw_provider is not None:
                events.extend(collect(
                    etw_provider.name,
                    etw_provider.collect_snapshot,
                ))

            publish_results = event_bus.publish(events)
            total += publish_results.get("store", 0)
            diagnostic_events = (
                diagnostic_monitor.poll()
                if diagnostic_monitor is not None
                else []
            )

            health_events: list[AIEEvent] = []
            if now >= next_health:
                health_events.append(health.to_event(host_id()))
                next_health = now + health_interval

            derived_events = [*diagnostic_events, *health_events]
            publish_results = event_bus.publish(derived_events)
            total += publish_results.get("store", 0)

            if on_diagnostic is not None:
                for event in diagnostic_events:
                    on_diagnostic(event)

            if on_cycle is not None:
                try:
                    on_cycle({
                        "status": "running",
                        "timestamp": time.time(),
                        "provider_health": health.snapshot().get("providers", {}),
                        "events_collected": len(events) + len(derived_events),
                        "providers": list(cycle_samples),
                    })
                except Exception:  # noqa: BLE001 - dashboard/telemetry listeners are non-critical.
                    pass

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
    finally:
        if etw_provider is not None:
            etw_provider.close()
        if output:
            output.close()
    return total
