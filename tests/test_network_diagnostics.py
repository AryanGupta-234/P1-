from aie.diagnostics.video_buffering import VideoMetrics, diagnose_video_buffering


def test_network_and_render_signals_are_distinct():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True, stall_count=3, observation_window_seconds=30,
        packet_loss_pct=0.0, throughput_mbps=20, estimated_required_mbps=5,
        rtt_ms=220, cpu_pct=95, dropped_frames_pct=8,
    ))
    causes = {finding.cause for finding in report.findings}
    assert "high_network_latency" in causes
    assert "local_decode_or_render_pressure" in causes
    assert "network_packet_loss" not in causes


def test_throughput_requires_both_measurements():
    report = diagnose_video_buffering(VideoMetrics(
        playback_stalled=True, stall_count=3, observation_window_seconds=30,
        throughput_mbps=2, estimated_required_mbps=None,
    ))
    assert "insufficient_streaming_throughput" not in {
        finding.cause for finding in report.findings
    }
