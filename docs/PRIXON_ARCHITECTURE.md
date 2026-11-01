# PRIXON Native Intelligence Architecture

**Status:** Initial architecture and runtime facade  
**Platform:** Windows 11 / AIE Windows-only codebase  
**Integration branch:** `dev`  
**Release target:** PRIXON 0.1.x  
**Last updated:** 2026-11-02

## North star

PRIXON is the native model identity and intelligence layer for AIE. It retains the learned capabilities of an approved upstream foundation model while AIE progressively owns the identity, context assembly, memory policy, knowledge retrieval, training data, evaluation, orchestration contracts and release process.

PRIXON is initially a **derived model/runtime**, not a foundation model trained from scratch. The upstream lineage must remain visible in the model manifest and model card. User-facing identity can be PRIXON without misrepresenting model provenance.

## 1. Preservation contract

The initial foundation target is Qwen2.5-7B-Instruct.

| Component | Decision | Contract |
|---|---|---|
| Original pretrained weights | Preserve | Keep an immutable, checksummed source checkpoint. Never overwrite it with a fine-tuned result. |
| Learned language and general knowledge | Preserve | Retain inherited representations and capabilities; evaluate for regressions after every adaptation. |
| Existing reasoning and instruction capability | Preserve and improve | Use adapters first; do not assume fine-tuning automatically improves reasoning. |
| Tokenizer and vocabulary | Preserve | Retain the compatible upstream tokenizer unless a separately evaluated tokenizer migration is approved. |
| Transformer architecture | Preserve initially | Keep the compatible Qwen2.5 architecture for the first derived releases. |
| Chat template | Preserve initially | Keep the provider-compatible Qwen/Ollama template. PRIXON supplies its own runtime system message; do not silently replace the template. |
| Qwen identity and runtime instructions | Override at the PRIXON boundary | Use PRIXON identity, release metadata and behavioural instructions. Upstream instruction-tuning tendencies may still exist in weights. |
| Memory | Extend under PRIXON policy | Reuse AIE's existing explicit, provenance-aware memory store. Do not create a second competing memory database. |
| Knowledge retrieval | Add PRIXON composition | Reuse AIE knowledge stores and add bounded source adapters/ranking as needed. Do not remove current retrieval. |
| Training pipeline | PRIXON-owned | Build dataset curation, provenance, licence review, deduplication, training manifests, adapter training and evaluation. Keep source weights immutable. |
| Model orchestration | PRIXON-facing, AIE-backed | Keep provider contracts, hardware-aware routing, planning and task orchestration. PRIXON adds identity/context orchestration through compatible interfaces. |
| Inference runtime | Retain Ollama first | Keep current Ollama adapter and provider contract. Add another backend only after parity tests. |
| Tool calling | Preserve AIE governance | Model outputs may propose typed plans. Tools/actions remain registered, allowlisted and policy-gated; the model never receives unrestricted OS execution. |

The upstream model's learned knowledge is encoded in its weights; the original pretraining corpus is not delivered as a browsable database. PRIXON does not claim ownership of, or access to, Qwen's original training corpus.

## 2. Existing AIE infrastructure to reuse

Do not duplicate or replace these modules during PRIXON's first milestone:

- `aie.models.base`: provider-independent `ChatMessage`, `ModelRequest` and `ModelResponse` contracts.
- `aie.models.ollama`: local Ollama inference/embedding adapter, installed-model checks, no implicit downloads and explicit remote-endpoint restrictions.
- `aie.models.router` and `aie.model_policy`: current local model routing and hardware/RAM guard.
- `aie.memory`: SQLite-backed explicit memories, provenance, sensitivity, expiry, revision/lineage and optional local semantic embeddings.
- `aie.knowledge`: curated Microsoft knowledge crawler and local document store.
- `aie.orchestration`: durable task plans/runs, state transitions and verification gates.
- `aie.policy`: capability manifests, approval, audit and execution controls.
- Existing event, session and context systems: explicit attachment and privacy boundaries remain in force.

The initial code in `aie.prixon` is a façade over those capabilities. It must not fork their storage, provider or policy logic.

## 3. Runtime flow

```text
User turn
   |
   v
PRIXON identity + versioned behavioural instructions
   |
   v
Explicit context policy (memory / knowledge disabled unless requested)
   |
   +---- existing AIE MemoryStore (sensitive excluded by default)
   |
   +---- existing AIE KnowledgeStore (source/provenance retained)
   |
   v
Bounded context packager (references marked as untrusted data)
   |
   v
Existing ModelRequest / LocalModelRouter
   |
   v
Existing Ollama adapter (Qwen-compatible model and chat template)
   |
   v
PRIXON response envelope + attached reference IDs
   |
   v
AIE's existing plan/policy/approval/verification path when actions are needed
```

Retrieved content is reference data, not executable instruction. Memory/knowledge is not silently attached to every request. The caller must explicitly enable each context source for a turn. Cloud egress remains governed by AIE's existing explicit per-request egress controls; this PRIXON runtime targets local routing.

## 4. Current implementation boundary

Implemented in the first PRIXON slice:

- A versioned PRIXON identity and foundation-lineage descriptor.
- A PRIXON runtime façade that consumes the existing AIE model-router contract.
- Explicit opt-in retrieval from existing MemoryStore and KnowledgeStore interfaces.
- Bounded, provenance-labelled context references, with retrieved material framed as untrusted.
- A response envelope that exposes the actual backend model/provider and the references attached to the turn.
- Unit tests for identity, preserved foundation-model reporting, opt-in context and missing-store errors.

Not yet implemented:

- A full PRIXON model registry and immutable checkpoint checksum inventory.
- Model adapters or merged PRIXON weights.
- A new generic multi-source document ingestion pipeline.
- Dataset registry, curation UI, licence/provenance validation and training orchestration.
- LoRA/QLoRA training, adapter composition or adapter release packaging.
- Dedicated held-out model benchmarks, regression gates and forgetting measurements.
- Independent inference backend; Ollama remains the supported initial backend.
- Automatic memory extraction/consolidation; existing user-review and explicit capture policies remain authoritative.
- Autonomous tool execution; existing AIE plan, policy, approval and verification layers remain authoritative.

## 5. Target repository structure

The first slice should stay small and reuse current modules:

```text
aie/
  prixon/
    __init__.py
    identity.py
    context.py
    runtime.py
    registry.py              # planned: immutable foundation/adapters metadata
    model_manifest.py        # planned: lineage, hashes, tokenizer/template metadata
    training/
      datasets.py            # planned: dataset manifests and validation
      adapters.py            # planned: LoRA/QLoRA orchestration
      promotion.py           # planned: evaluation-gated promotion
    evaluation/
      capability_suite.py    # planned: general + specialist regression suite
      memory_suite.py        # planned: retrieval/forgetting benchmarks
      reports.py             # planned: reproducible evaluation reports

aie/models/                  # existing provider contracts, Ollama, router
aie/memory/                  # existing persistent memory and embeddings
aie/knowledge/               # existing local knowledge store/crawler
aie/orchestration/           # existing planning and durable task runs
aie/policy/                  # existing approval, audit and execution gates
tests/
  test_prixon_runtime.py
docs/
  PRIXON_ARCHITECTURE.md
  adr/
    0001-prixon-foundation-and-runtime-boundaries.md
```

Do not add empty placeholder modules merely to make the tree look complete. Add each planned module with its contract, implementation and tests when its milestone begins.

## 6. Training and release policy

1. Preserve a checksummed, read-only copy of the approved Qwen2.5-7B-Instruct foundation checkpoint.
2. Record upstream model ID, revision, licence, tokenizer revision, chat-template revision and source notices in the model manifest.
3. Build PRIXON datasets from independently licensed, provenance-tracked sources and reviewed AIE examples. Do not claim access to Qwen's original pretraining dataset.
4. Deduplicate, remove sensitive/private data, validate labels, detect train/evaluation contamination and split by task family/source.
5. Begin with LoRA/QLoRA adapters; keep adapters separate from the foundation weights.
6. Evaluate general reasoning, instruction following, coding, structured output, tool/plan validity, specialist diagnostics, context handling and safety against the frozen baseline.
7. Reject adapter promotion when critical capability regressions exceed predeclared thresholds. Maintain catastrophic-forgetting and retrieval-robustness tests.
8. Merge adapters only as a separately versioned derived checkpoint after evaluation. Never overwrite the source foundation.
9. Publish a PRIXON model card, complete upstream attribution, adapter/training-data provenance, licence notices and a change summary for every release.

Training is not run as an always-on background process. Dataset generation, training and release promotion are deliberate, resource-budgeted jobs.

## 7. Identity and provenance

PRIXON is the runtime/product identity. The actual model returned by the backend remains recorded in every response and diagnostic log. The technical model card must state the upstream Qwen lineage and all modifications. PRIXON branding must not imply that the upstream weights were independently authored.

The system prompt changes at the runtime boundary. It does not remove behaviour learned during upstream instruction tuning. A future behavioural adapter may strengthen PRIXON behaviour, but must pass the same regression suite.

## 8. Resource policy for the Windows development host

- Preserve the existing AIE RAM-aware model router and single-inference/resource guards.
- Default to one local model inference at a time.
- Do not load 3B and 7B models concurrently on the 16 GB target.
- Do not auto-pull models or silently switch to cloud inference.
- Perform dataset preparation and model training as separate, explicitly launched jobs; use external GPU compute when local RAM/compute is insufficient.
- Keep observation and memory storage functional when no model is installed or Ollama is offline.

## 9. Acceptance criteria

PRIXON runtime is ready for wider integration when:

- The original Qwen checkpoint, tokenizer, architecture and chat template remain unchanged.
- The runtime uses PRIXON identity without misrepresenting model lineage.
- Existing AIE provider contracts, RAM-aware routing, memory, knowledge, orchestration and policy tests continue passing.
- Memory and knowledge are attached only when explicitly requested, are bounded and preserve provenance.
- Retrieved content cannot directly invoke tools or bypass AIE policy.
- The response records the real backend model/provider and context reference IDs.
- Baseline-vs-PRIXON evaluation shows no unreviewed regression in existing capabilities.
- Windows CI and target Windows 11 validation are recorded separately.

## References

- [AIE system architecture](ARCHITECTURE.md)
- [AIE architecture spotlight](ARCHITECTURE_SPOTLIGHT.md)
- [AIE roadmap](ROADMAP.md)
- [Development streams](DEVELOPMENT_STREAMS.md)
