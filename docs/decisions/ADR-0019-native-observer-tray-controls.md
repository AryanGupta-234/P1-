# ADR-0019: Native Observer Tray Controls

## Status

Accepted

## Context

The observer has local CLI pause/resume controls, but a Windows-first personal assistant needs a visible and accessible way to inspect observer status without opening a terminal or silently starting a collector.

## Decision

Provide a small Win32 notification-area controller with a status dialog and explicit Pause observation, Resume observation and Exit tray menu items. Pause/resume use the existing per-user observer pause marker; status displays only the paused state and the count of locally stored events. The tray does not start observation, enable providers, alter retention, execute capabilities or transmit data.

The native window and icon are created only on Windows. The controller is a foreground process started by the user with `aie tray`; it is not installed as a service or registered for automatic startup.

## Consequences

The tray is a lifecycle/status control surface, not a full dashboard or notification delivery subsystem. Permission settings, event-detail history, native notification policy and a complete desktop experience remain future work. The CLI remains available and is the source of truth for provider configuration.
