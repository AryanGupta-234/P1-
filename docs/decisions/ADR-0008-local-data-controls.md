# ADR-0008: Explicit Local Data Export and Deletion Controls

## Status

Accepted

## Context

AIE retains normalized observations locally. The architecture requires users to be
able to inspect, export and delete retained data, while active observers may otherwise
repopulate the store during destructive operations.

## Decision

Provide three explicit local controls:

- `aie health` displays provider health metadata without rendering observation payloads.
- `aie export <path>` writes JSONL event records; sensitive records are excluded unless
  `--include-sensitive` is explicitly supplied.
- `aie delete-all --confirm` performs permanent deletion only when the global observer
  pause marker is active.

The event-store API enforces that exports cannot overwrite the SQLite database itself.
These controls do not affect memory, policy-audit or task-session databases.

## Consequences

Export is useful for user review and debugging, but exported files become user-managed
copies and may contain sensitive data when explicitly requested. Delete-all prevents
repopulation races by requiring observation pause. A future desktop UI may wrap these
same APIs but must preserve the same confirmation and pause semantics.
