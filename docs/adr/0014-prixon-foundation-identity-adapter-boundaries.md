# ADR-0014: PRIXON foundation, identity and adapter boundaries

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decision owners:** AIE project

## Context

PRIXON should become a distinct personal assistant without discarding the general and specialist
capabilities already learned by Qwen2.5-7B-Instruct. Training from scratch is outside the initial
hardware, data and compute budget. The assistant should understand profanity, slang and offensive
vocabulary in legitimate context without removing AIE's independent safeguards for consequential
Windows actions.

## Decisions

1. Pin Qwen2.5-7B-Instruct by immutable Hugging Face commit SHA for every experiment.
2. Preserve the original foundation weights, architecture, tokenizer/vocabulary and Qwen chat template.
3. Add PRIXON identity at runtime and through separate adapter training; never overwrite the base.
4. The first QLoRA adapter is limited to `identity`, `conversation_style` and
   `contextual_language`.
5. General reasoning, coding, mathematics, planning, structured output, Windows, networking,
   cybersecurity and troubleshooting are held-out preservation/regression areas in the first phase.
6. Training records require source, licence, approval and data-classification provenance. Explicit
   consent is mandatory for user-contributed data. Private/sensitive records and credentials are
   forbidden in the Kaggle corpus.
7. Kaggle is a temporary GPU training worker. The repository remains the source of truth for
   configs, dataset manifests, evaluation prompts and adapter release metadata.
8. Contextual language understanding is distinct from permission to execute a system action.
   Existing AIE capability policy, approval, audit, execution gate and rollback remain authoritative.
9. Adapter promotion requires held-out regression testing and human review. The foundation remains
   independently loadable for comparison and rollback.

## Consequences

- Initial development can begin with a modest identity/context adapter without attempting to relearn
  Qwen's reasoning or specialist knowledge.
- Prompt and adapter changes can influence behaviour but cannot be represented as complete erasure
  of behaviours learned during original instruction tuning.
- The first adapter is a candidate until target-device and regression validation pass.
- No unrestricted command execution, policy bypass or safety-layer removal is introduced.
