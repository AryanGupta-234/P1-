# ADR-0018: Verified Task Skill Induction

## Status

Accepted

## Context

Memory retrieval and user feedback are useful for personalization, but a model-generated claim of success is not evidence that a procedure worked. Persisting unreviewed reasoning as procedural memory could reinforce hallucinations or unsafe steps.

## Decision

A procedural-skill candidate may be generated only from a completed task run containing at least one positively verified `verify` step. For action-bearing runs, every action step must reference an approved policy proposal with a successful immutable execution receipt, the audit chain must verify, and a positive verification step must depend transitively on each action step.

The candidate is deterministic: it is assembled from the original plan descriptions, success criteria and bounded completed-step summaries. No model is asked to rewrite the workflow. The candidate is displayed for review and is saved only with a separate explicit CLI confirmation. It is saved as procedural memory with the source task-run ID as provenance and is marked sensitive by default. Users may explicitly choose internal sensitivity.

This operation does not retrain, fine-tune, update prompts, or automatically turn the candidate into an executable capability.

## Consequences

The task run must remain in local storage for provenance validation. Memories can be searched and corrected under the normal sensitivity controls. Only user-reviewed, positively verified procedures are eligible. Plan quality, skill transfer and long-term improvement still require separate evaluation before any autonomous learning path is enabled.
