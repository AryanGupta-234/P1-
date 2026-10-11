"""Tests for bounded, read-only network probes."""
from __future__ import annotations

import pytest

from aie.providers.network import ProbeTarget, WindowsNetworkProvider, _dns_timing_ms, _tcp_connect_latency_ms


def test_provider_refuses_non_windows(monkeypatch):
    monkeypatch.setattr("aie.providers.network.os.name", "posix")
    with pytest.raises(OSError):
        WindowsNetworkProvider()


def test_probe_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr("aie.providers.network.os.name", "nt")
    with pytest.raises(ValueError):
        WindowsNetworkProvider(timeout_seconds=30)


def test_external_target_count_is_bounded(monkeypatch):
    monkeypatch.setattr("aie.providers.network.os.name", "nt")
    with pytest.raises(ValueError):
        WindowsNetworkProvider(
            external_targets=[
                ProbeTarget(str(index), "localhost")
                for index in range(5)
            ]
        )


def test_tcp_probe_returns_none_on_connection_error(monkeypatch):
    import socket
    def fail(*args, **kwargs):
        raise OSError("unreachable")
    monkeypatch.setattr(socket, "create_connection", fail)
    assert _tcp_connect_latency_ms("127.0.0.1", 443, 0.1) is None


def test_dns_probe_returns_none_when_resolution_fails(monkeypatch):
    import socket
    def fail(*args, **kwargs):
        raise socket.gaierror("no resolver")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert _dns_timing_ms("nohost.invalid", 0.5) is None


def test_collect_snapshot_emits_normalized_events(monkeypatch):
    from types import SimpleNamespace

    import aie.providers.network as network_module

    monkeypatch.setattr(network_module.os, "name", "nt")
    monkeypatch.setattr(
        network_module.psutil,
        "net_if_stats",
        lambda: {"Ethernet": SimpleNamespace(isup=True, speed=1000, mtu=1500)},
    )
    monkeypatch.setattr(network_module.psutil, "net_io_counters", lambda pernic=True: {})
    monkeypatch.setattr(network_module, "_default_gateway", lambda: None)
    monkeypatch.setattr(network_module, "_tcp_connect_latency_ms", lambda *args: 30.0)
    monkeypatch.setattr(network_module, "_dns_timing_ms", lambda *args: 12.0)

    provider = WindowsNetworkProvider(
        external_targets=[ProbeTarget("test_endpoint", "example.test")]
    )
    events = provider.collect_snapshot()

    assert [event.event_type for event in events] == [
        "network.interface.snapshot",
        "network.external_probe",
        "network.dns_probe",
    ]
    assert all(event.source == "windows.network" for event in events)
    assert events[1].data["connect_latency_ms"] == 30.0
    assert events[2].data["resolution_ms"] == 12.0


def test_dns_probe_does_not_spawn_unbounded_workers(monkeypatch):
    import socket
    import threading

    import aie.providers.network as network_module

    resolver_started = threading.Event()
    release_resolver = threading.Event()
    resolver_finished = threading.Event()

    def slow_resolver(*args, **kwargs):
        resolver_started.set()
        release_resolver.wait(2.0)
        resolver_finished.set()

    monkeypatch.setattr(socket, "getaddrinfo", slow_resolver)
    first_result = []
    caller = threading.Thread(
        target=lambda: first_result.append(network_module._dns_timing_ms("slow.test", 0.1))
    )
    caller.start()

    assert resolver_started.wait(1.0)
    assert network_module._dns_timing_ms("second.test", 0.1) is None
    caller.join(timeout=1.0)

    # Keep the underlying resolver blocked until the caller's bounded wait expires.
    assert not caller.is_alive()
    assert first_result == [None]

    release_resolver.set()
    assert resolver_finished.wait(1.0)
    assert network_module._DNS_PROBE_LOCK.acquire(timeout=1.0)
    network_module._DNS_PROBE_LOCK.release()
