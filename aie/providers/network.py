"""Bounded, read-only Windows network telemetry.

The provider measures interface counters, TCP connection-establishment latency to a
small allowlist of endpoints, and DNS resolution latency. It never changes network
configuration and never runs an unbounded probe.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import psutil

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


_DNS_PROBE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    """An explicitly selected endpoint for a bounded TCP reachability sample."""

    name: str
    host: str
    port: int = 443
    timeout_seconds: float = 1.5


def _tcp_rtt_ms(host: str, port: int, timeout: float) -> float | None:
    """Return TCP connect latency; None means the endpoint did not connect in time."""
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return round((time.perf_counter() - started) * 1000, 2)
    except (OSError, TimeoutError):
        return None


def _dns_timing_ms(host: str, timeout: float) -> float | None:
    """Measure resolver latency with a bounded wait on the caller's thread."""
    if not _DNS_PROBE_LOCK.acquire(blocking=False):
        return None
    result: list[float | None] = [None]
    completed = threading.Event()

    def resolve() -> None:
        started = time.perf_counter()
        try:
            socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            result[0] = round((time.perf_counter() - started) * 1000, 2)
        except OSError:
            result[0] = None
        finally:
            completed.set()
            _DNS_PROBE_LOCK.release()

    worker = threading.Thread(target=resolve, daemon=True, name="aie-dns-probe")
    try:
        worker.start()
    except RuntimeError:
        _DNS_PROBE_LOCK.release()
        return None
    completed.wait(max(0.1, min(timeout, 5.0)))
    return result[0] if completed.is_set() else None


def _default_gateway() -> str | None:
    """Read the active IPv4 default gateway using the Windows route utility."""
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["route.exe", "print", "-4"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 3 and columns[0] == "0.0.0.0" and columns[1] == "0.0.0.0":
            gateway = columns[2]
            if gateway and gateway != "0.0.0.0":
                return gateway
    return None


class WindowsNetworkProvider:
    """Collect bounded network observations; no mutation or configuration changes."""

    name = "windows.network"

    def __init__(
        self,
        *,
        external_targets: Iterable[ProbeTarget] | None = None,
        dns_host: str = "www.microsoft.com",
        timeout_seconds: float = 1.5,
    ) -> None:
        if os.name != "nt":
            raise OSError("AIE currently supports native Windows only.")
        if not 0.1 <= timeout_seconds <= 5.0:
            raise ValueError("timeout_seconds must be between 0.1 and 5.0")
        targets = tuple(external_targets or (
            ProbeTarget("https_primary", "www.microsoft.com", 443, timeout_seconds),
            ProbeTarget("https_secondary", "www.cloudflare.com", 443, timeout_seconds),
        ))
        if len(targets) > 4:
            raise ValueError("at most four external probe targets are allowed")
        if any(not 1 <= target.port <= 65535 for target in targets):
            raise ValueError("probe target ports must be between 1 and 65535")
        if any(not 0.1 <= target.timeout_seconds <= 5.0 for target in targets):
            raise ValueError("probe target timeouts must be between 0.1 and 5.0 seconds")
        self.external_targets = targets
        self.dns_host = dns_host
        self.timeout_seconds = timeout_seconds

    def collect_snapshot(self) -> list[AIEEvent]:
        """Collect one snapshot with a fixed upper bound on endpoint count/timeouts."""
        events: list[AIEEvent] = []
        interfaces = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)

        for name, state in sorted(interfaces.items()):
            counter = counters.get(name)
            events.append(AIEEvent(
                host_id=host_id(),
                source=self.name,
                event_type="network.interface.snapshot",
                entity=EntityRef(type="network_interface", name=name),
                data={
                    "is_up": bool(state.isup),
                    "speed_mbps": state.speed,
                    "mtu": state.mtu,
                    "bytes_sent": counter.bytes_sent if counter else None,
                    "bytes_received": counter.bytes_recv if counter else None,
                    "packets_sent": counter.packets_sent if counter else None,
                    "packets_received": counter.packets_recv if counter else None,
                    "errors_in": counter.errin if counter else None,
                    "errors_out": counter.errout if counter else None,
                    "drops_in": counter.dropin if counter else None,
                    "drops_out": counter.dropout if counter else None,
                },
                sensitivity="internal",
            ))

        gateway = _default_gateway()
        if gateway:
            gateway_rtt = _tcp_rtt_ms(gateway, 80, self.timeout_seconds)
            events.append(AIEEvent(
                host_id=host_id(),
                source=self.name,
                event_type="network.gateway_probe",
                entity=EntityRef(type="network_gateway", name="default_gateway"),
                data={
                    "rtt_ms": gateway_rtt,
                    "probe": "tcp_connect_port_80",
                    "target_is_private": True,
                },
                sensitivity="internal",
                confidence=0.9 if gateway_rtt is not None else 0.7,
                evidence_kind="observed",
            ))

        for target in self.external_targets:
            rtt = _tcp_rtt_ms(
                target.host, target.port, min(target.timeout_seconds, self.timeout_seconds)
            )
            events.append(AIEEvent(
                host_id=host_id(),
                source=self.name,
                event_type="network.external_probe",
                entity=EntityRef(type="network_endpoint", name=target.name),
                data={
                    "host": target.host,
                    "port": target.port,
                    "rtt_ms": rtt,
                    "probe": "tcp_connect",
                },
                sensitivity="internal",
                confidence=0.85 if rtt is not None else 0.65,
                evidence_kind="observed",
            ))

        dns_ms = _dns_timing_ms(self.dns_host, self.timeout_seconds)
        events.append(AIEEvent(
            host_id=host_id(),
            source=self.name,
            event_type="network.dns_probe",
            entity=EntityRef(type="dns_target", name=self.dns_host),
            data={"resolution_ms": dns_ms, "resolved": dns_ms is not None},
            sensitivity="internal",
            confidence=0.8 if dns_ms is not None else 0.6,
            evidence_kind="observed",
        ))
        return events
