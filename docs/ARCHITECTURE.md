# AIE System Architecture

## Layers
1. **Perception:** Windows-only host/process inventory and later allowlisted ETW/Event Log providers.
2. **Event infrastructure:** versioned events, local durable store, deduplication and reconciliation. SQLite first; distributed broker only when justified.
3. **Context:** temporal correlation and state. Observations and generated hypotheses remain distinct.
4. **Cognitive control plane:** goals, reasoning, planning, routing and arbitration. Deterministic code owns validation and state transitions.
5. **Memory and learning:** working, episodic, semantic, procedural and prospective memory with provenance, confidence, sensitivity, verification and expiry.
6. **Action plane:** capability registry, policy broker, approval, sandbox, verification and rollback. No unrestricted shell or administrator access.
7. **Governance:** identity, audit, privacy, observability and evaluation.

## Hybrid placement
- Local: collection, raw events, sensitive memory, policy enforcement and routine inference.
- Cloud: optional advanced reasoning/workers after explicit minimization and authorization.
- Observer remains usable offline without a model.

## Event flow
```text
Windows Provider -> Adapter -> Validation -> Privacy Filter
 -> SQLite Store -> State Reconciliation -> Context (future)
 -> Cognitive Core (future) -> Policy Broker (future)
 -> Approved Executor (future) -> Outcome Verification
```

## Windows telemetry strategy
1. User-mode APIs for initial inventory.
2. ETW for selected documented providers and higher-fidelity lifecycle telemetry.
3. Windows Event Log for explicitly allowlisted channels.
4. WMI/CIM and Service Control Manager for inventory/state queries.
5. Signed driver only if evidence shows a genuine gap and a separate security review approves it.

ETW is not complete visibility by itself. Provider availability, permissions, session configuration, buffers and consumer throughput affect coverage. Keep periodic reconciliation.
