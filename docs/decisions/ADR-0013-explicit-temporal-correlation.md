# ADR-0013: Explicit Temporal Evidence Correlation

## Status

Accepted

## Context

Activity sessions provide broad temporal clustering, but some diagnostics need a
narrow, reusable way to relate explicit event types such as a playback snapshot and a
nearby network probe.

## Decision

Provide a rule-driven correlator with explicit anchor and related event types, bounded
time windows, bounded input age/results, and same-host matching by default.
The output contains only event IDs, host ID, observed event types and the time span.
It does not infer causality, intent or root cause.

## Consequences

Context consumers can define narrowly scoped correlations without duplicating timestamp
logic. Cross-host correlations remain possible only through an explicit rule flag.
Future causal reasoning must use this evidence as input and retain a separate hypothesis
representation with provenance and confidence boundaries.