# ADR-0010: Central Remote Model Egress Gateway

## Status

Accepted

## Context

AIE supports local-first inference and explicitly authorized remote model providers.
Scattered CLI checks are insufficient as the system grows because new context sources
could otherwise bypass the same consent, payload and redaction rules.

## Decision

All AIE CLI remote model requests pass through a central local gateway before the
network adapter:

- cloud and remote-Ollama channels require explicit per-request egress authorization;
- activity, memory and task-session context require independent confirmation;
- sensitive memory is never eligible for remote requests;
- total prompt payload is bounded;
- high-confidence credential patterns are redacted before transmission;
- the gateway writes only metadata to a local egress audit database, never prompt,
  response or secret content.

The remote adapters retain their own HTTPS/endpoint safety checks. No cloud fallback,
model pull or implicit remote routing is introduced.

## Consequences

This provides one policy boundary for new context types and an auditable record of
remote egress decisions without creating a second copy of user content. Redaction is
intentionally high-confidence only; it is not a general data-loss-prevention system.
A future DLP system must be evaluated separately.

The gateway does not make local inference remote, and it does not grant a model any
additional capability.
