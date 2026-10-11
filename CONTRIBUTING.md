# Contributing to AIE

## Branch model
- `main`: stable release baseline.
- `dev`: integration branch.
- `feat/<scope>`: feature work.
- `fix/<scope>`: targeted fixes.
- `integrate/<scope>`: controlled integration work.

Create feature branches from the latest `dev`.

## Windows setup
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

## Engineering rules
1. Windows 10/11 only; no Linux/WSL providers.
2. Collectors are read-only and emit versioned evidence, never actions.
3. Unknown measurements stay unknown, not zero.
4. Keep observed facts separate from inferred hypotheses.
5. Model output cannot grant permissions or modify policy.
6. OS actions require a capability broker, least privilege, budgets, audit and verification.
7. Browser observation is opt-in and limited to necessary signals.
8. Never commit credentials, private telemetry or real personal data.
9. Add deterministic tests and document failure modes.
10. Update Architecture Spotlight and Roadmap in the same PR.

## Pull requests
Branch from `dev`, keep scope focused, include safety implications and exact tests run, and target `dev`. Never state tests passed unless a local run or CI confirms it.
