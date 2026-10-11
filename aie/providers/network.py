"""Read-only Windows network observations with bounded probes.

This provider reports interface metadata, gateway/external reachability latency and DNS
resolution timings. It does not change adapters, routes, DNS, proxy settings or firewall rules.
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable

import psutil

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    name: str
    host: str
    port: int = 443
    timeout_seconds: float = 1.5


def _tcp_rtt_ms(host: str, port: int, timeout: float) -> float | None:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return round((time.perf_counter() - started) * 1000, 2)
    except (OSError, TimeoutError):
        return None


def _dns_timing_ms(host: str, timeout: float) -> float | None:
    # getaddrinfo has no portable per-call timeout; resolve on a daemon worker and
    # bound the wait. A stuck resolver cannot block this observer's main loop.
    import threading

    result: list[float | None] = [None]
    done = threading.Event()

    def resolve() -> None:
        start = time.perf_counter()
        try:
            socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            result[0] = round((time.perf_counter() - start) * 1000, 2)
        except OSError:
            result[0] = None
        finally:
            done.set()

    worker = threading.Thread(target=resolve, daemon=True, name="aie-dns-probe")
    worker.start()
    done.wait(max(0.1, min(timeout, 5.0)))
    return result[0] if done.is_set() else None


def _default_gateway() -> str | None:
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["route.exe", "print", "-4"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode:
        return None
    for line in completed.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 3 and columns[0] == "0.0.0.0" and columns[1] == "0.0.0.0":
            gateway = columns[2]
            if gateway and gateway != "0.0.0.0":
                return gateway
    return None


class WindowsNetworkProvider:
    """Bounded read-only network sample emitter."""

    name = "windows.network"

    def __init__(
        self,
        *,
        external_targets: Iterable[ProbeTarget] | None = None,
        dns_host: str = "www.microsoft.com",
        timeout_seconds: float = 1.5,
    ):
        if os.name != "nt":
            raise OSError("AIE currently supports native Windows only.")
        if not 0.1 <= timeout_seconds <= 5.0:
            raise ValueError("timeout_seconds must be between 0.1 and 5.0")
        self.external_targets = tuple(external_targets or (
            ProbeTarget("https_primary", "www.microsoft.com", 443, timeout_seconds),
            ProbeTarget("https_secondary", "www.cloudflare.com", 443, timeout_seconds),
        ))
        if len(self.external_targets) > 4:
            raise ValueError("at most four external probe targets are allowed")
        self.dns_host = dns_host
        self.timeout_seconds = timeout_seconds

    def collect_snapshot(self) -> list[AIEEvent]:
        events: list[AIEEvent] = []
        interfaces = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)
        for name, state in sorted(interfaces.items()):
            counter = counters.get(name)
            events.append(AIEEvent(
                host_id=host_id(), source=self.name, event_type="network.interface.snapshot",
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
                host_id=host_id(), source=self.name, event_type="network.gateway_probe",
                entity=EntityRef(type="network_gateway", name="default_gateway"),
                data={"rtt_ms": gateway_rtt, "probe": "tcp_connect_port_80",
                      "target_is_private": True},
                sensitivity="internal", confidence=0.9 if gateway_rtt is not None else 0.7,
                evidence_kind="observed",
            ))

        for target in self.external_targets:
            rtt = _tcp_rtt_ms(target.host, target.port,
                              min(target.timeout_seconds, self.timeout_seconds))
            events.append(AIEEvent(
                host_id=host_id(), source=self.name, event_type="network.external_probe",
                entity=EntityRef(type="network_endpoint", name=target.name),
                data={"host": target.host, "port": target.port, "rtt_ms": rtt,
                      "probe": "tcp_connect"},
                sensitivity="internal", confidence=0.85 if rtt is not None else 0.65,
                evidence_kind="observed",
            ))

        dns_ms = _dns_timing_ms(self.dns_host, self.timeout_seconds)
        events.append(AIEEvent(
            host_id=host_id(), source=self.name, event_type="network.dns_probe",
            entity=EntityRef(type="dns_target", name=self.dns_host),
            data={"resolution_ms": dns_ms, "resolved": dns_ms is not None},
            sensitivity="internal", confidence=0.8 if dns_ms is not None else 0.6,
            evidence_kind="observed",
        ))
        return events
