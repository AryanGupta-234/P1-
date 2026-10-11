# Video Intelligence

## Implemented
`aie/diagnostics/video_buffering.py` is a deterministic read-only triage function. It analyzes supplied telemetry and returns evidence-linked hypotheses for throughput, packet loss, latency and local decode/render pressure. It refuses root-cause claims from a short/single stall or missing measurements. Confidence values are heuristic, not calibrated probabilities.

## Not implemented
There is no live browser extension, screen observer, model reasoning or autonomous remediation yet. The network sampler is implemented as a read-only Windows provider and is wired into the observer CLI. A context correlator now joins synthetic/future `browser.video.snapshot` events with fresh same-host network evidence; it does not itself collect browser signals.

## Future browser signals
Use an explicit opt-in Edge/Chrome extension and collect only:
- Playback state transitions (playing, waiting/stalled, paused, ended).
- Stall count/duration and playback-position deltas.
- Buffered-ahead duration.
- Browser-provided dropped/decoded frame counters where supported.
- Coarse site origin only when user permits it.

Never collect page text, credentials, cookies, form fields, browsing history or arbitrary DOM content. The separate foreground-window observer also omits window titles by default because they can contain private document names, chat titles or email subjects. Provide site-level and global pause controls. Prefer structured local IPC/native messaging to a local service.

## Future network signals
- Interface/link status and Wi-Fi signal via supported Windows APIs.
- Gateway and external TCP connection-establishment latency as separate signals; do not label it packet RTT.
- DNS timing as its own metric.
- Sustained throughput checks only with opt-in, strict duration/volume limits and backoff.
- Explicit timeouts and bounded sample frequency.

TCP connect duration includes connection setup (and may include name resolution when the target is a hostname); it is not a pure packet RTT. A failed TCP connection to a specific port does not prove the gateway or endpoint is unreachable. ICMP ping does not establish stream throughput or CDN health. Diagnostics must not alter DNS, adapters, routes or proxy settings.

## Remediation
`observation -> correlated evidence -> hypothesis -> proposal -> policy -> approval if needed -> bounded execution -> verification -> audit/memory`

Changing stream quality could become a low-risk, pre-authorized action if the site exposes a supported control. Network resets, process termination, service changes or OS configuration changes require approval and a recovery path.

## Evaluation
Add synthetic traces for congestion, Wi-Fi loss, decode pressure, remote-service failure and insufficient evidence. Measure precision/recall and false-positive rates before unattended recommendations.


## Browser extension prototype

The MV3 extension is in `browser_extension/`. It monitors HTML video elements only after the user enables it in the extension popup. It forwards playback state, a rolling stall count, buffered-ahead duration, playback-progress delta and available dropped-frame deltas. It does not send page URLs/origins, titles, text, media source URLs, screenshots, audio, cookies, credentials, form values or browsing history.

The extension requires HTTP/HTTPS site access to work across different video websites. That broad site permission is shown by Chrome/Edge; monitoring itself defaults to off and can be toggled off at any time. No telemetry is sent to a cloud endpoint.

### Install for local development (Chrome or Edge)
1. Install AIE into the Windows virtual environment: `python -m pip install -e .`.
2. Open `chrome://extensions` or `edge://extensions`, enable Developer mode, and choose **Load unpacked**.
3. Select the repository's `browser_extension` directory and copy its extension ID.
4. In PowerShell, run `scripts/register-native-host.ps1 -ExtensionId <ID> -Browser Chrome` (or `-Browser Edge`).
5. Restart the browser, open the extension popup, and explicitly enable monitoring.
6. Run `aie events` to inspect locally stored playback events.

The registration helper writes a per-user native-messaging manifest under `%LOCALAPPDATA%\AIE` and registers it under HKCU. Use `scripts/unregister-native-host.ps1` to remove the selected browser registration. The native host accepts only the documented metric fields and rejects unexpected fields.

### Limitations
This first observer sees HTML video elements, not proprietary playback internals. Some streaming sites may use protected or embedded players where counters are unavailable. It does not measure sustained throughput or packet loss; those remain unknown until a separate telemetry source measures them.
