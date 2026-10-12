# ADR-0020: Conservative Memory Conflict Review

## Status

Accepted

## Context

Memory records can express different preferences or facts over time. High lexical overlap alone cannot establish that one record contradicts another, and model-generated conflict resolution could silently replace user intent.

## Decision

Add a review-only detector for records with the same memory kind, explicit opposing lexical markers and shared non-marker context tokens. Sensitive records remain excluded unless the caller opts in. Candidates expose memory IDs, shared tokens and the opposing marker pair, not source content. The detector does not rewrite, merge, supersede, delete or re-rank memories.

The marker list is intentionally small and deterministic. It does not resolve negation scope, modality, temporal changes, conditional statements or factual entailment. The output is a prompt for human inspection only.

## Consequences

Potential conflicts can be triaged without automatic edits. The detector favors false negatives and must not be represented as natural-language understanding or contradiction proof. Full temporal conflict resolution and evaluation remain future work.
