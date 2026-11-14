# ADR-0017: SENTI Owns Its Runtime, Data and Capability Boundaries

- **Status:** Accepted for Phase 1 implementation
- **Date:** 2026-11-05
- **Decision owner:** SENTI project operator

## Context

The earlier SENTI planning draft proposed reusing AIE model, memory, planning, policy and Windows observer internals, and migrating AIE database files. The operator has explicitly clarified that SENTI must be a separate assistant product, not an AIE subsystem. SENTI may live on an isolated feature branch in the existing Git repository during development, but runtime and data ownership remain independent.

## Decision

1. SENTI owns its Python package (`senti/`), runtime lifecycle, configuration, Ollama transport, prompt composition, capability registry, approvals interface, Windows adapters and persistence layer.
2. The SENTI package must not import from `aie/`, `SENTINEL/`, or the SENTINEL dashboard. Automated AST tests enforce this boundary.
3. SENTI calls Ollama directly through Python HTTP APIs on loopback. Normal inference sends `think: false` in the `/api/chat` JSON request. No CLI invocation, CMD/PowerShell subprocess, or shell-based model call is permitted.
4. SENTI's canonical store is `%LOCALAPPDATA%\SENTI\senti.sqlite3`, resolved through SENTI-owned configuration. No AIE database migration or sharing is permitted. Conversation persistence and collection of window titles are opt-in and off by default.
5. The SENTINEL product remains separate. Any later connection must use a separately documented, versioned, read-only integration contract and explicit operator opt-in. No direct database sharing or UI embedding is allowed.
6. The SENTI model may propose tool calls only. The SENTI host validates schemas, checks availability and permissions, obtains approval for mutation, invokes registered adapters and records bounded outcomes.
7. Desktop UI is deferred. Phase 1 exposes an in-process Python service API for the future independent UI.
8. Windows-only actions are validated on Windows CI and the operator's Windows 11 device. Non-Windows development can test contracts and fake providers only.

## Consequences

- SENTI may duplicate architectural concepts already present in AIE. This is intentional: the product boundary and independent release lifecycle take precedence over code reuse.
- Existing AIE and SENTINEL files are not rewritten, imported, migrated, or modified by the SENTI package.
- Any old implementation-plan text suggesting AIE reuse, AIE database paths, or AIE-owned policy is superseded by this ADR for SENTI implementation.
- The implementation is a Windows automation foundation, not a claim that every Windows or third-party UI is universally controllable. Capability status and verification are reported per adapter.
