import pytest

from aie.diagnostics.video_buffering import VideoMetrics, diagnose_video_buffering


def test_single_short_stall_does_not_guess_a_cause():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True, stall_count=1, observation_window_seconds=5,
        packet_loss_pct=8.0,
    ))
    assert report.status == "insufficient_evidence"
    assert report.findings == ()


def test_no_stall_returns_no_stall():
    report = diagnose_video_buffering(VideoMetrics(playback_stalled=False))
    assert report.status == "no_stall"
    assert not report.findings


def test_network_and_local_render_findings_are_separate():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True, stall_count=4, observation_window_seconds=45,
        packet_loss_pct=3.5, throughput_mbps=3.0, estimated_required_mbps=8.0,
        cpu_pct=94.0, dropped_frames_pct=9.0,
    ))
    causes = {finding.cause for finding in report.findings}
    assert report.status == "findings"
    assert "network_packet_loss" in causes
    assert "insufficient_streaming_throughput" in causes
    assert "local_decode_or_render_pressure" in causes
    assert all(0.0 <= finding.confidence <= 1.0 for finding in report.findings)


def test_unknown_metrics_are_not_treated_as_zero():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True, stall_count=3, observation_window_seconds=30,
    ))
    assert report.status == "insufficient_evidence"


def test_invalid_metrics_are_rejected():
    with pytest.raises(ValueError):
        VideoMetrics(playback_stalled=True, packet_loss_pct=101)
