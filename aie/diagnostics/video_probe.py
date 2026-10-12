"""Bounded, explicitly invoked network probes for video troubleshooting.

Targets are supplied by the user. No probe runs during ordinary observation.
Throughput tests use HTTPS only, reject redirects/private destinations, and read a
strict byte cap. Packet-loss tests use a fixed number of Windows ping requests.
"""
from __future__ import annotations

import http.client
import ipaddress
import math
import os
import re
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlsplit


class VideoProbeError(ValueError):
    """A requested diagnostic probe could not be run safely."""


@dataclass(frozen=True, slots=True)
class PacketLossResult:
    label: str
    packets_sent: int
    packets_received: int

    @property
    def packet_loss_pct(self) -> float:
        return round(100.0 * (self.packets_sent - self.packets_received) / self.packets_sent, 2)


@dataclass(frozen=True, slots=True)
class ThroughputResult:
    bytes_received: int
    elapsed_seconds: float
    throughput_mbps: float
    samples_completed: int


@dataclass(frozen=True, slots=True)
class VideoProbeResult:
    packet_results: tuple[PacketLossResult, ...]
    throughput: ThroughputResult | None
    estimated_required_mbps: float | None

    @property
    def packet_loss_pct(self) -> float | None:
        sent = sum(item.packets_sent for item in self.packet_results)
        received = sum(item.packets_received for item in self.packet_results)
        if not sent:
            return None
        return round(100.0 * (sent - received) / sent, 2)

    @property
    def packets_sent(self) -> int:
        return sum(item.packets_sent for item in self.packet_results)

    @property
    def packets_received(self) -> int:
        return sum(item.packets_received for item in self.packet_results)

    @property
    def target_labels(self) -> tuple[str, ...]:
        return tuple(item.label for item in self.packet_results)


_LABEL_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_packet_target(label: str, host: str) -> tuple[str, str]:
    """Validate a user-supplied label and DNS name/IP without shell syntax."""
    label = label.strip().casefold()
    host = host.strip().rstrip(".")
    if not _LABEL_RE.fullmatch(label):
        raise VideoProbeError("target label must be 1-24 characters: a-z, 0-9, _ or -")
    if not host or len(host) > 253 or host.startswith("-") or any(c.isspace() for c in host):
        raise VideoProbeError("packet target must be a DNS hostname or IP address")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not all(_HOST_LABEL_RE.fullmatch(part) for part in host.split(".")):
            raise VideoProbeError("packet target must be a valid DNS hostname or IP address")
    return label, host


def measure_packet_loss(
    label: str,
    host: str,
    *,
    packets: int = 4,
    timeout_ms: int = 750,
    runner=subprocess.run,
) -> PacketLossResult:
    """Send a fixed number of one-shot pings and count successful responses.

    A non-zero exit code of 1 means no reply to that packet. Other exit codes
    indicate a command/runtime error and are not misreported as packet loss.
    """
    if os.name != "nt":
        raise VideoProbeError("packet-loss measurement is supported only on native Windows")
    label, host = validate_packet_target(label, host)
    if not 1 <= packets <= 4:
        raise VideoProbeError("packets must be between 1 and 4")
    if not 100 <= timeout_ms <= 1500:
        raise VideoProbeError("timeout_ms must be between 100 and 1500")

    try:
        address = ipaddress.ip_address(host)
        family = "-6" if address.version == 6 else "-4"
    except ValueError:
        family = "-4"

    received = 0
    for _ in range(packets):
        command = ["ping.exe", family, "-n", "1", "-w", str(timeout_ms), host]
        try:
            completed = runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=(timeout_ms / 1000.0) + 1.5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VideoProbeError(f"ping probe failed: {type(exc).__name__}") from exc
        if completed.returncode == 0:
            received += 1
        elif completed.returncode != 1:
            raise VideoProbeError(f"ping probe returned an unexpected exit code: {completed.returncode}")

    return PacketLossResult(label, packets, received)


def _validate_public_https_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 2048:
        raise VideoProbeError("throughput URL must be a valid HTTPS URL no longer than 2048 characters")
    parsed = urlsplit(url)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise VideoProbeError("throughput URL must use public HTTPS on port 443 without embedded credentials or fragments")
    host = parsed.hostname
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise VideoProbeError("throughput endpoint DNS resolution failed") from exc
    resolved = {entry[4][0] for entry in addresses}
    if not resolved:
        raise VideoProbeError("throughput endpoint did not resolve to an address")
    try:
        for address in resolved:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise VideoProbeError("throughput endpoint must resolve only to public IP addresses")
    except ValueError as exc:
        raise VideoProbeError("throughput endpoint resolved to an invalid IP address") from exc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path


def measure_https_throughput(
    url: str,
    *,
    timeout_seconds: float = 7.0,
    max_bytes: int = 768 * 1024,
    sample_bytes: int = 256 * 1024,
    clock=time.monotonic,
    connection_factory=http.client.HTTPSConnection,
) -> ThroughputResult:
    """Measure a short multi-request HTTPS download without storing its URL/body.

    It uses up to three 256 KiB range requests (768 KiB total), refuses redirects,
    and never downloads more than max_bytes. This is a path sample, not a claim
    about the bitrate or CDN serving the current video.
    """
    if not 1.0 <= timeout_seconds <= 10.0:
        raise VideoProbeError("timeout_seconds must be between 1 and 10")
    if not 64 * 1024 <= max_bytes <= 1024 * 1024:
        raise VideoProbeError("max_bytes must be between 64 KiB and 1 MiB")
    if not 16 * 1024 <= sample_bytes <= 512 * 1024:
        raise VideoProbeError("sample_bytes must be between 16 KiB and 512 KiB")

    host, path = _validate_public_https_url(url)
    started = clock()
    deadline = started + timeout_seconds
    total_bytes = 0
    samples_completed = 0
    request_index = 0

    while total_bytes < max_bytes and request_index < 3:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        requested = min(sample_bytes, max_bytes - total_bytes)
        connection = None
        try:
            connection = connection_factory(
                host,
                443,
                timeout=min(2.0, remaining),
                context=ssl.create_default_context(),
            )
            start_byte = request_index * sample_bytes
            end_byte = start_byte + requested - 1
            connection.request(
                "GET",
                path,
                headers={
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Range": f"bytes={start_byte}-{end_byte}",
                    "User-Agent": "AIE-Video-Diagnostic/1.0",
                },
            )
            response = connection.getresponse()
            if response.status not in (200, 206):
                raise VideoProbeError(
                    "throughput endpoint must return HTTP 200/206; redirects are not followed"
                )
            remaining_sample = requested
            while remaining_sample > 0:
                remaining_time = deadline - clock()
                if remaining_time <= 0:
                    break
                if connection.sock is not None:
                    connection.sock.settimeout(min(1.0, remaining_time))
                chunk = response.read(min(64 * 1024, remaining_sample))
                if not chunk:
                    break
                total_bytes += len(chunk)
                remaining_sample -= len(chunk)
            samples_completed += 1
            response.close()
            request_index += 1
            if remaining_sample > 0:
                break
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            if total_bytes == 0:
                raise VideoProbeError(f"throughput sample failed: {type(exc).__name__}") from exc
            break
        finally:
            if connection is not None:
                connection.close()

    elapsed = max(0.001, clock() - started)
    if total_bytes < 16 * 1024:
        raise VideoProbeError("throughput endpoint returned too little data for a useful sample")
    mbps = total_bytes * 8 / elapsed / 1_000_000
    if not math.isfinite(mbps) or mbps < 0:
        raise VideoProbeError("throughput sample produced an invalid measurement")
    return ThroughputResult(total_bytes, elapsed, round(mbps, 3), samples_completed)


def run_video_network_probe(
    *,
    packet_targets: tuple[tuple[str, str], ...] = (),
    throughput_url: str | None = None,
    estimated_required_mbps: float | None = None,
    packets: int = 4,
    timeout_ms: int = 750,
) -> VideoProbeResult:
    """Run only the probes explicitly supplied by the user."""
    if not packet_targets and not throughput_url:
        raise VideoProbeError("provide --packet-target and/or --throughput-url")
    if len(packet_targets) > 2:
        raise VideoProbeError("at most two packet targets are allowed")
    if estimated_required_mbps is not None and (
        not math.isfinite(estimated_required_mbps) or not 0 < estimated_required_mbps <= 10000
    ):
        raise VideoProbeError("estimated_required_mbps must be greater than 0 and no more than 10000")

    labels: set[str] = set()
    packet_results: list[PacketLossResult] = []
    for label, host in packet_targets:
        normalized_label, normalized_host = validate_packet_target(label, host)
        if normalized_label in labels:
            raise VideoProbeError("packet target labels must be unique")
        labels.add(normalized_label)
        packet_results.append(
            measure_packet_loss(normalized_label, normalized_host, packets=packets, timeout_ms=timeout_ms)
        )

    throughput = measure_https_throughput(throughput_url) if throughput_url else None
    return VideoProbeResult(tuple(packet_results), throughput, estimated_required_mbps)
