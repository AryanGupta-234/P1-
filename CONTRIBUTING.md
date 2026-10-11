# Contributing

1. Read the architecture spotlight, architecture and relevant ADR.
2. Keep this project Windows-only; no Linux/WSL providers.
3. Keep perception read-only. Actions belong behind a future policy broker.
4. Use versioned Pydantic event contracts.
5. Separate observed evidence from inferred hypotheses.
6. Add deterministic tests, including access-denied/provider-unavailable cases.
7. Minimize collection: no keylogging, covert recording, credential collection or arbitrary content surveillance.
8. Update ROADMAP.md and ARCHITECTURE_SPOTLIGHT.md in the same change.
9. Never commit secrets, local databases or personal telemetry.

Checks: `python -m pytest` and `ruff check .`.
