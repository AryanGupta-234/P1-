import socket
from types import SimpleNamespace

import pytest

from aie.diagnostics import video_probe


def test_packet_loss_counts_only_successful_one_shot_replies(monkeypatch):
    monkeypatch.setattr(video_probe.os, "name", "nt")
    results = iter([
        SimpleNamespace(returncode=0),
        SimpleNamespace(returncode=1),
        SimpleNamespace(returncode=0),
        SimpleNamespace(returncode=0),
    ])
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is False
        assert kwargs["timeout"] <= 3
        return next(results)

    result = video_probe.measure_packet_loss(
        "gateway", "192.168.1.1", packets=4, runner=runner
    )

    assert result.packets_sent == 4
    assert result.packets_received == 3
    assert result.packet_loss_pct == 25.0
    assert len(commands) == 4
    assert all(command[:5] == ["ping.exe", "-4", "-n", "1", "-w"] for command in commands)


def test_packet_loss_rejects_unbounded_or_unsafe_targets(monkeypatch):
    monkeypatch.setattr(video_probe.os, "name", "nt")
    with pytest.raises(video_probe.VideoProbeError):
        video_probe.validate_packet_target("bad label", "example.com")
    with pytest.raises(video_probe.VideoProbeError):
        video_probe.validate_packet_target("stream", "-n 100 example.com")
    with pytest.raises(video_probe.VideoProbeError):
        video_probe.measure_packet_loss("gateway", "192.168.1.1", packets=5)
    with pytest.raises(video_probe.VideoProbeError, match="native Windows"):
        monkeypatch.setattr(video_probe.os, "name", "posix")
        video_probe.measure_packet_loss("gateway", "192.168.1.1")


def test_packet_loss_runtime_error_is_not_reported_as_packet_loss(monkeypatch):
    monkeypatch.setattr(video_probe.os, "name", "nt")

    def runner(command, **kwargs):
        return SimpleNamespace(returncode=2)

    with pytest.raises(video_probe.VideoProbeError, match="unexpected exit code"):
        video_probe.measure_packet_loss("gateway", "192.168.1.1", runner=runner)


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeResponse:
    status = 206

    def __init__(self, size):
        self.remaining = size
        self.closed = False

    def read(self, size):
        count = min(size, self.remaining)
        self.remaining -= count
        return b"x" * count

    def close(self):
        self.closed = True


class FakeHTTPSConnection:
    def __init__(self, host, port, *, timeout, context):
        assert host == "speed.example"
        assert port == 443
        assert timeout <= 2
        assert context is not None
        self.sock = FakeSocket()
        self.request_args = None
        self.response = None
        self.closed = False

    def connect(self):
        self.connected = True

    def request(self, method, path, *, headers):
        assert self.connected
        self.request_args = (method, path, headers)

    def getresponse(self):
        self.response = FakeResponse(16 * 1024)
        return self.response

    def close(self):
        self.closed = True


def test_https_throughput_is_capped_and_aggregated(monkeypatch):
    monkeypatch.setattr(
        video_probe.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )
    connections = []

    def factory(*args, **kwargs):
        connection = FakeHTTPSConnection(*args, **kwargs)
        connections.append(connection)
        return connection

    result = video_probe.measure_https_throughput(
        "https://speed.example/sample.bin",
        timeout_seconds=5,
        max_bytes=64 * 1024,
        sample_bytes=16 * 1024,
        clock=lambda: 10.0,
        connection_factory=factory,
    )

    assert result.bytes_received == 48 * 1024
    assert result.samples_completed == 3
    assert result.throughput_mbps > 0
    assert len(connections) == 3
    assert all(c.request_args[0] == "GET" for c in connections)
    assert all(c.request_args[2]["Range"].startswith("bytes=") for c in connections)
    assert all(c.closed and c.response.closed for c in connections)


@pytest.mark.parametrize(
    "url",
    [
        "http://speed.example/file",
        "https://user:password@speed.example/file",
        "https://speed.example:8443/file",
        "https://speed.example/file#fragment",
    ],
)
def test_throughput_rejects_insecure_or_ambiguous_urls(url):
    with pytest.raises(video_probe.VideoProbeError):
        video_probe._validate_public_https_url(url)


def test_throughput_rejects_private_dns_destinations(monkeypatch):
    monkeypatch.setattr(
        video_probe.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(video_probe.VideoProbeError):
        video_probe.measure_https_throughput("https://speed.example/file")


def test_throughput_never_follows_redirects(monkeypatch):
    monkeypatch.setattr(
        video_probe.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )

    class RedirectConnection(FakeHTTPSConnection):
        def getresponse(self):
            return SimpleNamespace(status=302, close=lambda: None)

    with pytest.raises(video_probe.VideoProbeError, match="redirects are not followed"):
        video_probe.measure_https_throughput(
            "https://speed.example/redirect",
            connection_factory=RedirectConnection,
        )


def test_combined_probe_requires_at_least_one_explicit_target():
    with pytest.raises(video_probe.VideoProbeError):
        video_probe.run_video_network_probe()


def test_multi_target_packet_loss_is_not_collapsed_into_one_percentage():
    result = video_probe.VideoProbeResult(
        packet_results=(
            video_probe.PacketLossResult("gateway", 4, 3),
            video_probe.PacketLossResult("video_path", 4, 4),
        ),
        throughput=None,
        estimated_required_mbps=None,
    )

    assert result.packet_loss_pct is None
    assert result.packets_sent == 8
    assert result.packets_received == 7


def test_single_target_packet_loss_is_available_as_one_scoped_value():
    result = video_probe.VideoProbeResult(
        packet_results=(video_probe.PacketLossResult("gateway", 4, 3),),
        throughput=None,
        estimated_required_mbps=None,
    )

    assert result.packet_loss_pct == 25.0

def test_target_dns_resolution_is_bounded_and_returns_a_pinned_ip(monkeypatch):
    monkeypatch.setattr(
        video_probe.socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", port, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port)),
        ],
    )

    assert video_probe._resolve_addresses_bounded("example.test", 443) == (
        ("1.1.1.1", socket.AF_INET),
        ("2606:4700:4700::1111", socket.AF_INET6),
    )


def test_target_dns_resolution_rejects_invalid_returned_addresses(monkeypatch):
    monkeypatch.setattr(
        video_probe.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 443))
        ],
    )

    with pytest.raises(video_probe.VideoProbeError, match="DNS resolution failed"):
        video_probe._resolve_addresses_bounded("example.test", 443)


def test_packet_probe_uses_resolved_ip_not_original_hostname(monkeypatch):
    monkeypatch.setattr(video_probe.os, "name", "nt")
    monkeypatch.setattr(
        video_probe.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0))
        ],
    )
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    result = video_probe.measure_packet_loss(
        "gateway", "example.test", packets=1, runner=runner
    )

    assert result.packets_received == 1
    assert commands[0][-1] == "1.1.1.1"

def test_throughput_rejects_invalid_port():
    with pytest.raises(video_probe.VideoProbeError, match="invalid port"):
        video_probe._validate_public_https_url("https://speed.example:99999/file")


@pytest.mark.parametrize("estimate", [True, 10 ** 10000])
def test_probe_rejects_boolean_or_oversized_bitrate_estimate(estimate):
    with pytest.raises(video_probe.VideoProbeError, match="estimated_required_mbps"):
        video_probe.run_video_network_probe(
            packet_targets=(("gateway", "192.168.1.1"),),
            estimated_required_mbps=estimate,
        )

def test_pinned_https_connection_uses_validated_ip_and_original_tls_hostname(monkeypatch):
    raw_socket = object()
    wrapped_socket = object()
    connect_calls = []
    wrap_calls = []

    class FakeContext:
        check_hostname = True
        verify_mode = video_probe.ssl.CERT_REQUIRED

        def wrap_socket(self, sock, *, server_hostname):
            wrap_calls.append((sock, server_hostname))
            return wrapped_socket

    def create_connection(address, *, timeout, source_address):
        connect_calls.append((address, timeout, source_address))
        return raw_socket

    monkeypatch.setattr(video_probe.socket, "create_connection", create_connection)
    connection = video_probe._PinnedHTTPSConnection(
        "speed.example",
        "1.1.1.1",
        443,
        timeout=1.5,
        context=FakeContext(),
    )
    connection.connect()

    assert connect_calls == [(("1.1.1.1", 443), 1.5, None)]
    assert wrap_calls == [(raw_socket, "speed.example")]
    assert connection.sock is wrapped_socket

