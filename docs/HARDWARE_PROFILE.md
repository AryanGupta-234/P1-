# AIE Development Hardware Profile

This is a sanitized development target profile based on the maintainer-provided `systeminfo` and `ollama list` output. It intentionally excludes account identifiers, Windows Product ID, private/public IP addresses, DHCP details and other unique network identifiers.

## Machine target

| Property | Value |
|---|---|
| Device family | ASUS Vivobook X1605ZA |
| OS | Windows 11 Home Single Language, x64 |
| Reported build | 10.0.26300 |
| CPU | Intel Core i5-12500H class, 12 cores / 16 threads |
| Installed memory | 16 GB (approximately 15.7 GiB usable) |
| Virtualization | Hypervisor detected |
| Virtualization-based security | Running |
| Hypervisor-enforced Code Integrity | Running |
| Kernel-mode Hardware-enforced Stack Protection | Running |
| App Control for Business | Enforced |
| Networking | Wi-Fi plus VirtualBox and TAP virtual adapters |

The OS build and security posture are environment facts, not permission to alter boot policy, disable protections or install a driver.

## Locally available Ollama models

| Model | Local role | AIE policy |
|---|---|---|
| `qwen2.5:3b-instruct` | Routine language tasks | Default local reasoning model |
| `qwen2.5:7b-instruct` | More demanding reasoning | Escalate only when free memory is sufficient |
| `nomic-embed-text:latest` | Embeddings | Semantic retrieval / memory indexing |

AIE must detect local model availability through the Ollama local endpoint rather than assume that this profile is current. Never auto-pull models.

## Resource policy

- Keep perception and event storage model-independent.
- Use the 3B model by default for routine tasks.
- Use the 7B model only when the task is complex, the model is installed, and available RAM is above a conservative threshold (initial default: 7.5 GiB).
- If memory is tight, stay on 3B or return a deterministic result. Do not load multiple models concurrently by default.
- Use Nomic only for embedding workloads; do not route general chat to an embedding model.
- Cloud escalation remains disabled unless the user explicitly enables the task and data-egress policy.

## Runtime tuning

For this 16 GB host, begin with one Ollama inference at a time and a modest context window. Measure actual resident memory and latency before increasing context length or parallelism. Model quantization and KV-cache settings affect real memory use; model file size alone is not a sufficient estimate.

Suggested starting environment (set only in the AIE/Ollama launch configuration, not system-wide without review):

```powershell
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
```

AIE should not modify Windows pagefile settings or terminate user applications to make room for inference.

## Security compatibility

VBS, HVCI, Kernel-mode Hardware-enforced Stack Protection and App Control are part of the target baseline. AIE must coexist with these protections. Kernel-mode experimentation is out of scope for the user-mode observer and requires a separate signed-driver design and test environment.
