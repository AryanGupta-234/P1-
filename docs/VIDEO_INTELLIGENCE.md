# Video Intelligence

## Implemented pipeline

1. **Browser observation:** the opt-in Chrome/Edge MV3 extension observes HTML video elements after the user enables monitoring. It reports playback state, a rolling stall count, buffered-ahead duration, playback-position delta and dropped-frame deltas when the browser exposes them.
2. **Local transport:** the extension sends a strict native-messaging payload to the Windows host. The host rejects unknown fields and stores normalized `browser.video.snapshot` events in the local SQLite store.
3. **Windows telemetry:** a bounded read-only provider samples interface counters, TCP connection-establishment latency to a private gateway and two public endpoints, and DNS resolution timing.
4. **Foreground context:** the Windows foreground observer records app/process transitions without reading window titles by default. It samples the active process CPU, RSS memory, thread count and process I/O counters on a bounded cadence.
5. **Context assembly:** `aie.context.video` correlates fresh browser, same-host foreground-app and network observations. It never copies window-title text into the resulting context.
6. **Diagnostics:** `aie.diagnostics.video_buffering` produces conservative evidence-backed hypotheses. The `aie context` command displays the latest context and hypotheses.

## Diagnostic logic

A diagnosis requires repeated stalls and a minimum observation window (defaults: at least 2 stalls over at least 20 seconds). A single stall or short sample is reported as insufficient evidence.

Available hypotheses include:
- **Stream buffer starvation:** little buffered media ahead (default threshold 0.75 seconds). This suggests that the player is running out of buffered media; it does not prove a network fault or distinguish CDN/server issues from local connectivity.
- **Playback pipeline not advancing with buffer available:** at least 5 seconds buffered while playback progress is effectively zero. Inspect the player/decoder/render path before changing networking.
- **Local decode/render pressure:** high foreground browser CPU together with elevated dropped-frame ratio.
- **Insufficient streaming throughput, packet loss or high packet RTT:** only evaluated when a source actually supplies those specific measurements. TCP connection-establishment time and aggregate interface bytes are not substituted for packet RTT, stream throughput or packet loss.

Thresholds and confidence values are heuristics, not calibrated probabilities. Root-cause accuracy must be evaluated against representative traces before unattended remediation is enabled.

## Privacy and controls

- Extension monitoring defaults to **off** and has an explicit popup toggle.
- Content collection is limited to HTML video playback/performance signals. It does not send page URLs/origins, titles, text, media source URLs, screenshots, audio, cookies, credentials, form fields or browsing history.
- The extension requires HTTP/HTTPS site permission to operate across different video websites. That broad permission is visible in the browser's permission UI.
- Window titles are not collected by default. `--include-window-titles` is a separate explicit opt-in and marks the corresponding event as sensitive.
- `aie pause` pauses all AIE observer loops for the current Windows user; `aie resume` resumes them. Pausing does not delete stored events.
- The native host accepts only a strict, versioned metric allowlist. Browser content never becomes an action or a policy instruction.

## Install for local development (Chrome or Edge)

1. In PowerShell, install AIE into the Windows virtual environment: `python -m pip install -e .`.
2. Open `chrome://extensions` or `edge://extensions`, enable Developer mode, and choose **Load unpacked**.
3. Select the repository's `browser_extension` directory and copy its extension ID.
4. Register the host: `scripts/register-native-host.ps1 -ExtensionId <ID> -Browser Chrome` (or `-Browser Edge`).
5. Restart the browser, open the extension popup, and explicitly enable monitoring.
6. Start AIE: `aie observe --duration 3600`.
7. Inspect: `aie status`, `aie events`, and `aie context`.
8. Stop data collection immediately with `aie pause`; use `aie resume` to resume.

The registration helper writes a per-user native-messaging manifest under `%LOCALAPPDATA%\AIE` and registers it under HKCU. Use `scripts/unregister-native-host.ps1 -Browser Chrome` (or Edge) to remove the browser registration.

## Recording diagnostic outcomes
Use `aie events` to find a `diagnostic.video_finding` event ID, then run:

```powershell
aie feedback <EVENT_ID> --outcome resolved
aie feedback <EVENT_ID> --outcome not_resolved --note "Playback still stalls after quality change"
```

Supported outcomes are `resolved`, `not_resolved` and `not_attempted`. Feedback is stored as a separate local event linked to the finding; an optional note is marked sensitive. The data is not yet used to update model weights or automatically change future actions.

## Limitations and next validation

The extension sees HTML video elements, not proprietary player internals. Some protected or embedded players may expose no useful metrics. The network sampler does not measure sustained streaming throughput or packet loss. Native host registration and end-to-end operation still need validation on the target Windows desktop. No autonomous remediation is implemented: the current system diagnoses and suggests only.
