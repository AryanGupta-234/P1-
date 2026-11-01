# ADR 0001: PRIXON foundation and runtime ownership boundaries

- **Status:** Accepted for initial implementation
- **Date:** 2026-11-02
- **Decision owners:** AIE maintainers
- **Related:** [PRIXON Native Intelligence Architecture](../PRIXON_ARCHITECTURE.md)

## Context

AIE already has provider-independent model contracts, a local Ollama adapter, hardware-aware routing, explicit persistent memory, semantic memory embeddings, a curated local knowledge store, durable task orchestration and a policy/approval boundary. Replacing these components wholesale would duplicate mature functionality and risk capability regressions.

The objective is to create PRIXON as AIE's own model identity and intelligence layer while retaining the learned capabilities of an upstream open-weight foundation model.

## Decision

1. Use Qwen2.5-7B-Instruct as the initial derived-model foundation target, subject to a release-time licence and provenance audit.
2. Preserve an immutable original foundation checkpoint. Do not overwrite it with fine-tuned or merged weights.
3. Retain the compatible tokenizer, architecture and provider-managed chat template for initial releases.
4. Apply PRIXON identity and behavioural instructions at the runtime request boundary. A system prompt is not treated as a mechanism for erasing upstream instruction-tuned behaviour.
5. Reuse AIE's existing model contracts, Ollama adapter, model router, memory store, knowledge store, orchestration and policy systems. PRIXON adds a façade and new functionality only where a tested gap exists.
6. Attach memory and knowledge only under explicit per-request context flags. Sensitive memory remains excluded by default.
7. Keep tool proposals separate from tool execution. Existing AIE plan validation, policy, approval, audit and verification remain authoritative.
8. Develop PRIXON datasets and training/evaluation pipelines independently. Start with adapters, keep source weights frozen, and promote changes only after regression tests.
9. Keep Ollama as the initial inference backend. Backend replacement requires functional, security, resource and performance parity evidence.
10. Preserve upstream notices and publish model lineage, training-data provenance and modification disclosures for derived distributions.

## Consequences

### Positive

- Existing model, memory, retrieval and orchestration power is preserved.
- PRIXON can evolve its identity and specialist capabilities independently of Ollama.
- The original foundation remains available for rollback and capability comparison.
- New retrieval and training features can be introduced incrementally without creating competing stores.

### Trade-offs

- PRIXON 0.1 is a derived runtime/facade, not an independently pretrained foundation model.
- The underlying weights retain patterns from upstream instruction tuning; runtime prompts cannot completely erase those tendencies.
- PRIXON must continue to disclose Qwen lineage and comply with the exact licence of the checkpoint/adapters being distributed.
- Independent foundation training remains a separate long-term research programme.

## Rejected alternatives

- **Replace all Qwen/AIE infrastructure immediately:** rejected because it duplicates working code and risks regressions.
- **Train from scratch immediately:** rejected because the project does not yet have the data, compute or evaluation corpus needed to justify that cost.
- **Automatically merge or fine-tune every memory:** rejected because unverified or sensitive memories must not silently alter model weights.
- **Give the model unrestricted shell/tool execution:** rejected because action authorization belongs to AIE's external policy boundary.
