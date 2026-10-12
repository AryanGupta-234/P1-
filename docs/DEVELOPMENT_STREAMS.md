# Development streams

**Effective date:** 2026-10-12  
**Active development tracks:** `dev` and `browser-video-intelligence`  
**Stable release branch:** `main`

## 1. Overall AGI ecosystem — `dev`

This is the primary integration and development branch for the AIE ecosystem.

Ownership:
- Cognitive core, local model adapters, routing and reasoning.
- Planning, task orchestration, durable task state and recovery.
- Persistent memory, retrieval, consolidation, evaluation and learning.
- Windows environment perception, process/network/system observation and provider health.
- Policy broker, capability manifests, approvals, audit ledger, execution controls and verification.
- Shared event contracts, context/session intelligence, CLI and desktop experience.
- Cross-cutting architecture, security, CI and repository documentation.

Changes in this track must preserve Windows-only scope, local-first defaults, explicit data-egress controls, read-only observation, bounded capabilities and fail-closed execution.

## 2. Browser/video intelligence — `browser-video-intelligence`

This is the independent, long-lived development branch for browser and video intelligence. It was created from the integrated `dev` baseline on 2026-10-12, so it starts with the existing browser/video observer, native-host, telemetry, correlation and diagnostic foundation. New progress in this track stays on this branch until a milestone is ready for integration.

Ownership:
- Chrome/Edge extension and browser observer behavior.
- Windows native-messaging bridge and local browser-event persistence.
- Playback state, buffering, dropped-frame and available media timing telemetry.
- Correlation of playback evidence with fresh foreground-app and network observations.
- Video diagnostic hypotheses, incident deduplication, feedback and trace evaluation.
- Browser/video-specific tests, setup instructions and design documentation.

The observer remains opt-in and disabled by default. Do not collect cookies, credentials, form contents, page text or unrelated browsing content. Diagnostics recommend; they do not autonomously alter browser, network or operating-system settings.

## 3. Branch and integration rules

1. Keep the two active workstreams on their respective long-lived branches. Do not create additional persistent feature branches by default.
2. Keep `main` stable. Release changes flow from validated `dev`; no development work is performed directly on `main`.
3. Keep ecosystem-only changes on `dev`. Keep browser/video-only changes on `browser-video-intelligence`.
4. When shared contracts or common infrastructure change on `dev`, fast-forward `browser-video-intelligence` from `dev` after checking that the update is a clean fast-forward. Do not force-push or rewrite either branch.
5. Integrate browser/video work back into `dev` only at a reviewed milestone through a pull request from `browser-video-intelligence` to `dev`. Keep that pull request in draft until tests and target-desktop checks are complete.
6. Update the relevant roadmap and architecture notes as part of each milestone. Mark work DONE only when code, tests and validation evidence exist.
7. Retire historical branches and stale pull requests only after confirming their unique commits are merged or their functionality is superseded. Never delete or overwrite an unverified branch.

## 4. Current baseline

- The integrated ecosystem implementation is on `dev`, including the bounded planning/orchestration and policy-gated execution work merged on 2026-10-12.
- `browser-video-intelligence` starts from that same integrated commit and is the only active branch for further browser/video-specific progress.
- The first independent browser/video milestone remains target-desktop validation, trace-corpus construction and false-positive/false-negative evaluation. Hosted CI does not replace live Edge/Chrome and native-host testing on the Windows machine.
- `main` remains the stable branch and is not advanced by this branch reorganization.
