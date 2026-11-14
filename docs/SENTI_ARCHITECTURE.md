# SENTI Architecture

SENTI is a local-first personal AI operator for Windows 11. This document describes the system as implemented in version 0.2.x.

## Layers and responsibilities

| Layer | Where | Responsibility |
|---|---|---|
| Foundation model | Ollama `qwen3.5:4b` (weights unchanged) | Language, reasoning, tool-call generation |
| Model configuration | Private local Modelfile → Ollama tag `SENTI` (not in this repo) | Identity, personality, owner, purpose, truthfulness rules |
| Host runtime | `senti/runtime.py` | Sessions, context, dynamic thinking, tool loop, policy hand-off, learning |
| Semantic layer | `senti/semantic.py` | Local embeddings (`nomic-embed-text`) + fuzzy fallback for memory, experience and tool discovery |
| Capabilities | `senti/tools/*`, `senti/windows/*` | Typed tools with risk tiers, schemas, simulators and verification |
| Policy | `senti/tools/registry.py` | Validation, rate limits, emergency stop, simulation, approval, audit |
| Memory & learning | `senti/store.py`, `senti/learning.py` | Memories with provenance/correction, procedures and lessons from outcomes |
| Environment | `senti/environment.py` | Bounded background sampling and proactive insights |
| Console | `senti/ui/*` | Loopback, token-protected presentation and approval surface |
| Evaluation | `senti/evaluation.py` | Behaviour and latency suite against the real model |

A Modelfile change, a host prompt change, a new capability and a change to model weights are different things. SENTI changes the first three; weights are untouched (see "Model adaptation").

## Request lifecycle

understand → contextualize → reason → plan → authorize → execute → verify → learn

1. **Context.** The session's fixed system block = private identity + operating protocol + host profile + manifest + compact capability catalog. Per turn, the user message carries a small `[SENTI host]` note with relevant memories, recalled experience, open tasks (only when changed) and policy changes.
2. **Reasoning.** The model decides whether to chat, explain, investigate or act. There are no phrase or keyword routes. Deliberate thinking (`SENTI_THINK=auto`) turns on after a failed tool or when combining several sources of evidence.
3. **Tools.** The model gets full schemas for the core and most-used tools (learned from the audit trail) and can call anything in the catalog through `senti_invoke`. `senti_find_tools` searches capabilities by meaning.
4. **Authorization.** For every state-changing call the registry validates the arguments, runs the tool's simulator (current → intended state, effect, recovery) and passes the preview to the approval handler. The console shows it to the user. Emergency stop blocks all mutations. The model can never grant itself permissions.
5. **Execution and verification.** Providers return `summary`, data and a `verified` flag. Results are compacted before the model reads them.
6. **Learning.** Tool outcomes become `procedure` (worked) or `lesson` (failed) memories, recalled by meaning for similar goals. Users can correct memories (`senti_update_memory`); the previous value is kept as provenance.

## Performance design (CPU-only laptops)

Qwen3.5 is a hybrid recurrent/attention model. Ollama's llama-server can only reuse its cached state through *context checkpoints*, so any change to earlier prompt content forces re-reading. SENTI therefore:

- keeps each conversation an **append-only transcript** with a fixed system block and tool list;
- **primes** each session in the background (the expensive ~6k-token prefix is processed before the first message);
- **collapses finished tool turns** to "question → answer", because the template re-renders past tool turns differently from how they were generated;
- sends a **compact catalog** instead of full schemas for rarely used tools;
- **streams** reply tokens to the console;
- compacts tool results (drops noise fields, rounds numbers, bounds lists).

On the development laptop (i5-12500H, CPU inference) a primed chat reply starts in about 2 s. Turns that call tools cost extra model passes at roughly 6–10 generated tokens/s and 25–35 prompt tokens/s for small increments.

## Capability areas

Windows diagnostics and inventory; Settings / Control Panel / MMC / shell catalogue (517 static entries plus live discovery); application discovery, launch and uninstall; audio, display, power, radios, network, services, scheduled tasks, windows and UI Automation; approved-root file operations; documents (read txt/md/docx…, create txt/md); notes and reminders; tracked tasks; browser (open URL, web search, read a public HTTPS page); environment context and proactive insights; memory and experience.

## Safety boundaries

- The `senti/` package never shells out (no `subprocess`, `cmd`, PowerShell or `os.system`); a test enforces this.
- Mutations require host approval after simulation; previews never execute.
- No process termination, no UAC bypass, no security-control changes.
- Web reads are HTTPS-only, size-bounded, refuse private and loopback addresses, and are approval-gated. Content is treated as untrusted data.
- Environment sampling keeps app names only (no window titles or content) in memory. Only insights are persisted. Disable it with `SENTI_OBSERVE=false`.

## Model adaptation

Fine-tuning is deliberately not done yet. `python -m senti.evaluation` provides the baseline (identity, tool selection, truthfulness, reasoning, latency). Adaptation (for example a LoRA on SENTI-specific tool-use transcripts) is only justified if this suite shows a persistent gap that prompt, configuration or runtime changes cannot close. Any adapter must be compared on the same suite.
