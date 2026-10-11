# Video Intelligence — first diagnostic slice

## Scope delivered
The first video-buffering component is a deterministic, read-only triage function in `aie/diagnostics/video_buffering.py`. It accepts normalized telemetry and returns evidence-linked hypotheses. It does not capture a screen, inspect page content, control a browser, modify network settings, or execute fixes.

## Input contract
- `playback_stalled`: explicit playback-state signal from a future opt-in browser observer.
- `stall_count` and `observation_window_seconds`: repeated-stall evidence.
- `throughput_mbps` and `estimated_required_mbps`: sustained network capacity versus estimated stream demand.
- `rtt_ms` and `packet_loss_pct`: network quality indicators.
- `cpu_pct` and `dropped_frames_pct`: local resource/rendering indicators.

Unknown measurements must remain `None`; zero means a measured zero. The diagnostic refuses to infer a cause from a single stall or an insufficient observation window.

## Interpretation
The output ranks hypotheses for packet loss, insufficient throughput, high latency, and local decode/render pressure. Confidence values are heuristic ranking scores, not calibrated probabilities. Network tests alone cannot establish the cause of a CDN/server-side stall; future versions should add browser media telemetry and distinguish network, decoder, renderer, and remote-service signals.

## Safety boundary
This component is a pure function. It produces recommendations only. Browser quality changes, network resets, process termination, service changes, or other remediation require a separate capability broker, explicit action policy, audit trail, and post-action verification. No autonomous remediation is implemented by this slice.

## Next implementation steps
1. Add an opt-in Edge/Chrome extension or native-messaging bridge that reports only playback state and selected media timing counters—not page text, passwords, cookies, or form content.
2. Add a Windows network sampler with bounded timeouts and clear separation between gateway and external measurements.
3. Correlate browser and OS telemetry using timestamped evidence.
4. Build synthetic traces and evaluate false positives/negatives before enabling recommendations.
5. Add proposal/policy/approval/execution/verification infrastructure before any automated changes.
