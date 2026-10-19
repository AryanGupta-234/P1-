# ADR 0012 — Sentinel Prime dashboard interaction and presentation layer

- **Date:** 2026-10-19
- **Status:** Accepted
- **Branch:** `dev`

## Context

The Sentinel loopback dashboard had accumulated multiple generations of CSS overrides. Card edges, typography, spacing, navigation and responsive rules were inconsistent across its eight workspaces. The interface also relied on direct navigation and scattered action buttons, making a feature-rich agent harder to operate quickly.

## Decision

Restore the original gunmetal/steel visual palette with lime and orange accents, and replace the stacked stylesheet with one responsive design system. Use a grouped navigation rail, consistent page hierarchy, rounded layered surfaces, readable typography, restrained motion and explicit reduced-motion support.

Add a searchable command palette opened with `Ctrl+K`, plus workspace shortcuts `Ctrl+Shift+1` through `Ctrl+Shift+8`. The palette may open existing workspaces or dispatch only the existing allowlisted Sentinel jobs through their current UI handlers. It must reflect disabled job state and must not bypass Feature Control.

Make the main cockpit metrics keyboard-accessible drill-down surfaces for the related telemetry, evidence, feature-control and system-intelligence workspaces.

Keep the dashboard dependency-free and served from the existing authenticated loopback worker. Do not add new operating-system mutation, arbitrary command execution, remote UI services, or additional data collection as part of a presentation redesign.

## Consequences

- The eight workspaces share one visual language and responsive behavior.
- Repeated CSS overrides are removed, making future UI work easier to reason about.
- Common navigation and dispatch actions are faster to discover and keyboard-accessible.
- Existing command gating, user approval, local inference and privacy boundaries remain authoritative.
- The command palette is a client-side entry point only; the existing server endpoints remain the enforcement boundary.

## Validation

Source-level checks confirmed unique DOM IDs, no missing JavaScript ID lookups, matching navigation/screen IDs, valid view-jump targets, palette actions backed by existing command handlers, and balanced CSS braces. Target Windows 11 browser/WebView rendering, animation smoothness, accessibility/focus behavior and end-to-end interaction remain pending.
