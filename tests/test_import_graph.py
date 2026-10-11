def test_context_and_diagnostics_public_exports_load_without_cycles():
    from aie.context import ActivityTimeline, build_activity_timeline, build_video_observation_context
    from aie.diagnostics import VideoDiagnosticMonitor, VideoMetrics, diagnose_video_buffering

    assert ActivityTimeline is not None
    assert build_activity_timeline is not None
    assert build_video_observation_context is not None
    assert VideoDiagnosticMonitor is not None
    assert VideoMetrics is not None
    assert diagnose_video_buffering is not None
