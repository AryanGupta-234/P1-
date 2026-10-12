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

## Explicit network probes

Network probes are **never run by ordinary observation**. Start one manually while investigating a playback issue:

```powershell
# Probe packet loss to the local gateway and a user-selected video-path endpoint.
aie video-probe --packet-target gateway=192.168.1.1 --packet-target video_path=cdn.example.net

# Add an explicitly selected public HTTPS test object and a bitrate estimate for the chosen quality.
aie video-probe --throughput-url https://speed-test.example.net/1m.bin --estimated-required-mbps 8

# Show the latest correlated browser, foreground and network evidence.
aie context
```

- Packet loss sends at most four individual ICMP echo requests to each of at most two user-supplied targets. Target labels, counts and percentages are stored; target hostnames/IPs are not. Results remain separate by target. When two targets are selected, AIE does not average their percentages into one root-cause signal; run a single-target probe when you specifically want that endpoint's packet-loss value considered by the diagnostic rule.
- Throughput requires a user-supplied public HTTPS URL on port 443 that honors byte ranges with valid HTTP 206 Content-Range responses. The endpoint must resolve only to globally routable IPs. Credentials, fragments, redirects and private destinations are rejected. The client issues up to three range requests, reads at most 768 KiB by default (hard limit 1 MiB), and applies bounded DNS, connect, response and read timeouts. The URL, hostname and response bytes are never stored.
- ICMP can be filtered or deprioritized. Packet loss to a selected host is corroborating path evidence, not proof that the streaming CDN dropped media packets.
- HTTPS throughput measures the selected test object/path, not the active video CDN, stream bitrate or a guarantee of sustainable throughput. Supply `--estimated-required-mbps` only when you have an external estimate for the selected playback quality.
- A probe event is correlated only with fresh same-host video observations. Unknown values remain unknown.

## Synthetic trace evaluation

Run the bundled deterministic regression corpus:

```powershell
aie video-evaluate
```

The command reports exact cause-set match rate, micro precision/recall/F1 and per-cause TP/FP/FN/TN. A custom version-1 JSON corpus can be evaluated with `aie video-evaluate --dataset <PATH>`. Store numeric telemetry and labels only; do not include page URLs, media URLs, titles, cookies, account information or raw page content.

The bundled `video-diagnostics-synthetic-v1` corpus contains controlled scenarios for all diagnostic rules, insufficient evidence, and unknown metrics. It is **synthetic regression data**. A perfect score means the current rules match those authored examples; it is not real-world accuracy, field validation or confidence calibration. A consented, representative corpus from different players, networks and CDNs is still required for those claims.

## Consent-gated field trace preparation

After collecting real browser sessions on the target Windows machine, create a sanitized candidate file for independent review:

```powershell
aie video-trace-export --confirm --hours 24 --limit 100 --output .\video_field_trace_candidates.json
```

This command is explicitly opt-in, reads a bounded local time window, groups observations by playback session, and refuses to overwrite an existing output file. The export contains only bounded numeric playback/network/resource metrics and synthetic candidate IDs. It omits host IDs, event IDs, timestamps, process names, window titles, page/media URLs, destination hosts/IPs, page content and raw event payloads. The file is marked `dataset_kind: field_candidate` and is intentionally rejected by the evaluator until it is reviewed.

For each case, replace `expected_causes: null` with a manually verified list of cause IDs (or an empty list only when no cause is supported by independent evidence), then change `dataset_kind` to `field`. Do not treat AIE's own finding as ground truth. Keep the curated field dataset local unless every included measurement has been reviewed and explicitly approved for sharing. Run `aie video-evaluate --dataset <PATH>` after labeling.

The exporter makes field-corpus preparation repeatable; it does not create field truth automatically. Representative cross-player/CDN sampling, human adjudication, a held-out evaluation split and confidence calibration remain required.

## Privacy and controls

- Extension monitoring defaults to **off** and has an explicit popup toggle.
- Content collection is limited to HTML video playback/performance signals. It does not send page URLs/origins, titles, text, media source URLs, screenshots, audio, cookies, credentials, form fields or browsing history.
- The extension requires HTTP/HTTPS site permission to operate across different video websites. That broad permission is visible in the browser's permission UI.
- Window titles are not collected by default. `--include-window-titles` is a separate explicit opt-in and marks the corresponding event as sensitive.
- `aie pause` pauses all AIE observer loops for the current Windows user; `aie resume` resumes them. Pausing does not delete stored events.
- The native host accepts only a strict, versioned metric allowlist. Browser content never becomes an action or a policy instruction.

## Install for local development (Chrome or Edge)

1. In PowerShell, create and activate the repository virtual environment:
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -e .
   ```
2. Open `chrome://extensions` or `edge://extensions`, enable Developer mode, and choose **Load unpacked**.
3. Select the repository's `browser_extension` directory and copy its extension ID.
4. Register the host for that browser:
   ```powershell
   .\scripts\register-native-host.ps1 -ExtensionId <ID> -Browser Chrome
   # Or use -Browser Edge with that browser's extension ID.
   ```
5. Restart the browser, open the extension popup, and explicitly enable monitoring.
6. Start AIE in the activated virtual environment: `aie observe --duration 3600`.
7. Inspect: `aie status`, `aie events`, and `aie context`.
8. Run the read-only setup validator:
   ```powershell
   .\scripts\validate-target-desktop.ps1 -Browser Chrome,Edge
   .\scripts\validate-target-desktop.ps1 -Browser Chrome,Edge -RequireBrowserRegistration
   ```
   The second command fails when either selected browser is not registered. It checks the native-host manifest, extension origin, executable, required Python imports and bundled trace corpus; it does not modify the registry or browser configuration.
9. Stop data collection immediately with `aie pause`; use `aie resume` to resume.

The registration helper writes a per-user, browser-specific native-messaging manifest under `%LOCALAPPDATA%\AIE\native-host` and registers it under that browser's HKCU key. Chrome and Edge manifests are independent, so both browsers can be registered at the same time. Use `scripts/unregister-native-host.ps1 -Browser Chrome` (or Edge) to remove only that browser's registration and manifest.

## Recording diagnostic outcomes
Use `aie events` to find a `diagnostic.video_finding` event ID, then run:

```powershell
aie feedback <EVENT_ID> --outcome resolved
aie feedback <EVENT_ID> --outcome not_resolved --note "Playback still stalls after quality change"
```

Supported outcomes are `resolved`, `not_resolved` and `not_attempted`. Feedback is stored as a separate local event linked to the finding; an optional note is marked sensitive. The data is not yet used to update model weights or automatically change future actions.

## Limitations and next validation

The extension sees HTML video elements, not proprietary player internals. Some protected or embedded players may expose no useful metrics. The manual network probe measures a selected test object and ICMP targets, not the active CDN media connection. Native host registration, live player telemetry, browser restart/reconnect behavior and cross-player/CDN coverage still need validation on the target Windows desktop. A real field trace corpus and calibration study remain open. No autonomous remediation is implemented: the current system diagnoses and suggests only.
