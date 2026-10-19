# ADR 0013 — Sentinel local source auto-restart and dashboard recovery

- **Date:** 2026-10-19
- **Status:** Accepted
- **Branch:** `dev`

## Context

Continuous and privacy-sensitive collector settings require their worker pipelines to be reinitialized. Previously, Feature Control saved those changes but left restart responsibility to the operator. Likewise, a locally updated AIE Python package continued to run in the old worker process until manually restarted, and the embedded dashboard could remain on stale HTML/JavaScript.

## Decision

Add a default-enabled `auto_restart_enabled` Sentinel profile setting.

The worker hashes its installed AIE Python modules (plus the project `pyproject.toml`, when present) every two seconds. A change is accepted only after three consecutive identical snapshots. This debounce avoids restarting during partial file replacement or an in-progress repository/package update. The watcher observes local files only; it does not run `git pull`, install packages, fetch remote code or mutate the operating system.

The authenticated dashboard config endpoint compares saved settings against the continuous/advanced sensor restart allowlist. When one of those values changes and auto-restart is enabled, it schedules a restart after returning the save response. If auto-restart is disabled, the API reports that a restart is required but leaves the worker running.

Provide a global manual Restart action regardless of the auto-restart setting. Manual Stop removes a pending restart marker.

For a restart, request observer shutdown, close the loopback dashboard, record the reason, release the single-instance mutex, clear the marker files and launch a detached replacement worker. The replacement loads the persisted profile and reinitializes the collector graph. The dashboard detects the new worker PID, reconnects and reloads the newly served interface.

## Consequences

- Local code updates already present on disk are activated without manually restarting the worker.
- Sensor pipeline settings that require reinitialization are applied automatically when enabled.
- The operator retains an explicit auto-restart switch and a manual Restart action.
- The dashboard can update its embedded UI after the process replacement.
- Restart state and failure type are observable through the local status endpoint.
- No remote update channel, automatic source pull, package installation or OS-level restart is introduced.

## Validation

Source-level wiring has been inspected for configuration allowlisting, restart marker handoff, stable source snapshots, mutex release before replacement launch, header restart action, PID-change reload and profile controls. Target Windows 11 runtime validation, including real file updates, partial update debounce, configuration changes, manual restart, dashboard reconnection and restart-failure handling, remains pending.
