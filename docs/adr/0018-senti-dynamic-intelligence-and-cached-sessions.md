# ADR-0018: Dynamic intelligence, private identity and cached sessions

- **Status:** Accepted (SENTI 0.2)
- **Date:** 2026-11-14
- **Supersedes:** the `think=False`-only rule and host-side identity shortcuts of ADR-0017

## Decisions

1. **Identity lives in the private local Modelfile.** It is read from Ollama (`/api/show` `system`) at runtime and composed with the public operating protocol. It is never committed; the repository is public.
2. **No phrase or keyword routing.** The model chooses capabilities. The only hard-coded data is the Windows settings/Control Panel/shell catalogue. Meaning-based retrieval uses local embeddings with a fuzzy fallback.
3. **Dynamic thinking** (`auto|on|off`) replaces "thinking always off".
4. **Simulate before approve.** Every state-changing capability gets a dry-run preview, which is passed to the approval handler.
5. **Append-only, primed sessions with a compact catalog** keep CPU-only inference responsive. Finished tool turns are collapsed.
6. **Outcome learning, not weight training.** Procedures and lessons are memories; any fine-tuning must be justified by the evaluation suite.

## Consequences

- Rarely used tools are reached through `senti_invoke`. Policy, simulation and audit always see the real tool name.
- Changing tools or identity mid-session is avoided. New sessions pick up changes.
- Collapsed tool turns keep only the final answer in the transcript. The full trace stays in the audit log and learned experience.
