"""Tests for the opt-in bounded Windows network telemetry provider."""
from __future__ import annotations

import os

import pytest

from aie.providers.network import ProbeTarget, WindowsNetworkProvider, _dns_timing_ms, _tcp_rtt_ms


def test_provider_refuses_non_windows(monkeypatch):
    monkeypatch.setattr("aie.providers.network.os.name", "posix")
    with pytest.raises(OSError):
        WindowsNetworkProvider()


def test_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr("aie.providers.network.os.name", "nt")
    with pytest.raises(ValueError):
        WindowsNetworkProvider(timeout_seconds=30)


def test_external_target_count_is_bounded(monkeypatch):
    monkeypatch.setattr("aie.providers.network.os.name", "nt")
    targets = [ProbeTarget(str(i), "localhost") for i in range(5)]
    with pytest.raises(ValueError):
        WindowsNetworkProvider(external_targets=targets)


def test_tcp_probe_returns_none_on_connection_error(monkeypatch):
    import socket

    def fail(*args, **kwargs):
        raise OSError("unreachable")

    monkeypatch.setattr(socket, "create_connection", fail)
    assert _tcp_rtt_ms("127.0.0.1", 443, 0.1) is None


def test_dns_probe_returns_none_when_resolution_fails(monkeypatch):
    import socket

    def fail(*args, **kwargs):
        raise socket.gaierror("no resolver")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert _dns_timing_ms("invalid.test", 0.5) is None
