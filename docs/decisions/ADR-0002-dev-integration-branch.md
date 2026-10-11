# ADR-0002: Development Branch and Evidence-Driven Integration

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
Parallel development needs a stable integration target without destabilizing `main`. Some work exists on separate unmerged feature branches and must not be silently treated as part of the integration baseline.

## Decision
- `main` remains the stable baseline.
- `dev` is the integration branch.
- Scoped `feat/*`, `fix/*`, and `integrate/*` branches originate from the latest `dev`.
- Review and validate changes before merging into `dev`; promote validated releases from `dev` to `main` separately.
- Keep Architecture Spotlight and Roadmap synchronized with code.
- Never claim a feature or test is complete without implementation and validation evidence.

## Consequences
This supports incremental integration and protects stable releases. It adds review/CI overhead and requires contributors to keep their branches current. Unmerged feature-branch code is not part of the integration baseline.
