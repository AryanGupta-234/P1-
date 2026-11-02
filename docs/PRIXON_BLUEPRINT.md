# PRIXON — model and assistant implementation blueprint

**Status:** implementation baseline  
**Target:** Windows 11 runtime; Kaggle GPU training worker  
**Foundation:** Qwen2.5-7B-Instruct  
**Initial release type:** Qwen foundation plus a separate PRIXON LoRA adapter

## Non-negotiable foundation rule

The original Qwen checkpoint is an immutable upstream baseline. Pin and record its exact Hugging
Face commit SHA for every experiment. Preserve its architecture, original weights, tokenizer,
vocabulary and Qwen chat template. Never overwrite the upstream checkpoint. Training must produce
a separate adapter artifact. The adapter is not a new model trained from scratch.

The base model supplies existing general and specialist capabilities. PRIXON adds identity,
memory, retrieval, tools, orchestration and measured behaviour improvements around it.

## Preserve

- Learned general reasoning, multi-step problem solving, coding, mathematics, language understanding,
  planning and structured-output ability.
- Existing knowledge of Windows internals, networking, cybersecurity and troubleshooting.
- Foundation architecture, Qwen tokenizer/vocabulary and original chat template.
- A separately addressable, untouched foundation checkpoint for all comparisons and rollback.

Preservation is an engineering objective that must be demonstrated by benchmarks; it is not an
assumption that every answer is correct.

## Replace or build

- Assistant identity, personality and system instructions become PRIXON-owned.
- PRIXON runtime context composition, memory integration and provenance handling.
- PRIXON dataset factory, validation, split manifests, experiment registry and adapter lifecycle.
- Model-routing and specialist orchestration integration with existing AIE components.
- Contextual language behaviour: understand slang, profanity and offensive vocabulary in context,
  rather than using a blanket word filter or refusing benign linguistic/educational/analytical use.
- Independent action policy: preserve permissions, approval, audit and rollback for consequential
  operating-system actions. Conversation style never grants a capability.

## Initial training scope

The first QLoRA adapter is limited to the categories `identity`, `conversation_style` and
`contextual_language`. It must not attempt to relearn general reasoning, coding, mathematics,
Windows, networking, cybersecurity or troubleshooting. Those are holdout/regression areas and
should first be improved with retrieval, current documentation, telemetry and verified tools.

Do not train on arbitrary desktop logs. Every training example must have a unique ID, explicit
source provenance, licence, approval status and data-classification label. User-contributed
examples require explicit consent. Private or sensitive records and credentials are rejected.

## Data pipeline

The dependency-free validator at `aie/prixon/dataset.py` validates JSONL records, rejects unknown
licences, unreviewed samples, private/sensitive classification, missing consent, duplicate IDs
and exact duplicate conversations. It creates deterministic 80/10/10 train/validation/test splits
and SHA-256 manifests. Exact deduplication does not detect semantic near-duplicates; human review
and similarity screening remain required.

## Kaggle training

Use a Kaggle notebook as an ephemeral training worker, not as the project source of truth. The
repository owns source code, configs, dataset provenance and release records. The notebook resolves
the Qwen model commit SHA at run start, records it, uses 4-bit NF4 QLoRA and saves adapter weights
only. The initial starter settings are LoRA rank 16, alpha 32, dropout 0.05, batch size 1,
gradient accumulation 8, sequence length 2048 and one conservative epoch. Tune from measured
loss, memory and regression results rather than assuming those defaults are optimal.

Never upload the full foundation model as an output artifact. Never merge the adapter in the
initial phase. Kaggle accelerator options and weekly GPU quota can vary; inspect the active account
and session controls before training.

## Evaluation and release

Compare untouched Qwen and PRIXON adapter on the same held-out set. Keep prompt, generation
parameters, package versions, model revision, dataset split hashes, random seed and adapter
hashes. Human-review representative examples because exact-match and loss are not reliable
semantic quality measures.

Release gate:
1. Foundation revision and tokenizer identity match the experiment manifest.
2. Training dataset passed provenance, licence, consent and duplicate checks.
3. No private/sensitive data was included.
4. General reasoning, coding, math, structured output and planning do not materially regress.
5. Windows, networking, cybersecurity and troubleshooting regression sets do not materially regress.
6. Contextual-language examples improve without teaching the model to ignore action authorization.
7. No critical factuality, privacy or safety regression.
8. Adapter can be loaded, disabled and rolled back independently.

## Runtime integration

AIE remains Windows-first. Reuse existing model contracts/router, memory store, knowledge store,
planning/orchestration, policy broker and audit ledger. Do not introduce duplicate memory stores,
permission systems or model routers. Local inference remains the default. Cloud egress stays
explicitly opt-in and auditable.

## Current implementation state

Implemented in this first rebuild slice:
- PRIXON identity prompt and safe message composition helper.
- Strict JSONL validation and deterministic dataset splitting.
- Seed synthetic examples, QLoRA configuration and Kaggle starter notebook.
- Dataset unit tests.

Not yet implemented or verified:
- Wiring identity into every AIE inference entry point.
- Kaggle execution, GPU compatibility and adapter training.
- Full baseline/regression benchmark and human evaluation.
- Adapter registry, Windows Ollama/GGUF export and runtime loading.
- End-to-end Windows test execution.

Never mark these pending items as complete until evidence exists.
