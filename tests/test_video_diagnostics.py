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


def test_low_buffer_ahead_suggests_starvation_without_proving_network_fault():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True,
        stall_count=3,
        observation_window_seconds=30,
        buffered_ahead_seconds=0.2,
        playback_progress_delta_seconds=0.0,
    ))
    finding = next(item for item in report.findings if item.cause == "stream_buffer_starvation")

    assert finding.severity == "medium"
    assert finding.confidence < 1.0
    assert "does not prove a network fault" in finding.recommendation
    assert "network_packet_loss" not in {item.cause for item in report.findings}
    assert "insufficient_streaming_throughput" not in {
        item.cause for item in report.findings
    }


def test_buffered_media_with_no_progress_suggests_pipeline_investigation():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True,
        stall_count=4,
        observation_window_seconds=45,
        buffered_ahead_seconds=12.0,
        playback_progress_delta_seconds=0.0,
    ))
    assert "playback_pipeline_not_advancing_with_buffer" in {
        item.cause for item in report.findings
    }


def test_buffer_and_progress_ranges_are_validated():
    with pytest.raises(ValueError):
        VideoMetrics(playback_stalled=True, buffered_ahead_seconds=-1)
    with pytest.raises(ValueError):
        VideoMetrics(playback_stalled=True, playback_progress_delta_seconds=301)
