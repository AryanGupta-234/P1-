# ADR-0009: Heuristic Evidence Quality and Review-Only Memory Consolidation

## Status

Accepted

## Context

AIE needs stronger context quality without allowing heuristics or model-generated
similarity to silently become user intent, truth, or automatic memory mutation.

## Decision

The context layer provides:

- bounded freshness weighting for normalized events using a configurable half-life;
- a conservative, allowlisted contradiction detector for near-simultaneous conflicts in
  explicit state fields;
- a review-only memory consolidator that proposes duplicate/near-duplicate active
  memory pairs using bounded lexical/tag similarity.

Freshness weights are ranking aids, not calibrated probabilities. Contradiction detection
is deliberately narrow and does not attempt causal inference. Memory consolidation only
returns proposals; it cannot merge, delete, rewrite, reweight, or retrain.

Sensitive memories are excluded from consolidation by default. An explicit local option
can include them for review without printing memory contents.

## Consequences

These components make evidence quality and memory hygiene measurable while preserving
the user-controlled nature of memory. A later learning system may consume reviewed
outcomes, but any automatic merge or skill induction must add provenance, evaluation,
rollback and review boundaries first.
