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

    def request(self, method, path, *, headers):
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
