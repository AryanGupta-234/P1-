# SENTI

SENTI is a local-first personal AI operator for Windows 11, built by Aryan Gupta. It understands what you ask, investigates your real system state, previews and (with your approval) performs Windows operations, verifies the outcome, and learns from what worked.

SENTI runs entirely on your PC. Its language model is **Qwen3.5 4B** through a local [Ollama](https://ollama.com) install; SENTI's identity, personality and behaviour are its own.

## What it does

| Area | What SENTI can do |
|---|---|
| Conversation | Natural English and Hinglish, streamed replies, continuity across sessions |
| Diagnosis | Reads processes, memory, CPU, storage, network/DNS/DHCP, services, startup items, devices, event logs, Defender and Windows Update posture; reasons over the evidence |
| Windows surfaces | Searches and opens 500+ catalogued surfaces — every `ms-settings:` page, Control Panel items and applets, MMC consoles, management utilities, shell folders and hidden namespaces — plus live discovery of what is registered on this PC |
| Applications | Finds and opens any installed app (Win32, MSI, Store/MSIX) dynamically; uninstalls with the vendor uninstaller, MSI or Store removal and verifies removal |
| Automation | Volume, brightness, power plans, Wi-Fi/Bluetooth radios, DNS, adapters, services, scheduled tasks, windows, UI Automation, keyboard/mouse in a verified foreground window, approved file operations |
| Memory & learning | Remembers what you ask it to, accepts corrections (keeping the old value as provenance), records verified procedures and failed approaches, and recalls them by meaning |
| Tasks | Tracks your ongoing objectives with status, notes and due times, and follows up across sessions |
| Productivity | Notes, reminders, reading documents (txt, md, csv, docx and more) and creating new txt/md documents in your approved folders |
| Browser | Opens pages and web searches in your browser; reads a public HTTPS page's text (with approval) |
| Awareness | Background sampling of CPU, memory, disks, battery, network and the foreground app name, with proactive insights (memory pressure, low disk, due reminders…) that suggest a next step and never act on their own |

## How it works

Every request follows **understand → contextualize → reason → plan → authorize → execute → verify → learn**.

- **The model decides.** SENTI offers the model its full capability list and lets it choose; there are no keyword or phrase tables. Meaning-based retrieval (local `nomic-embed-text` embeddings) powers memory recall, experience recall and `senti_find_tools`.
- **Dynamic thinking.** Plain conversation stays fast; deliberate reasoning switches on when a tool fails or several sources of evidence have to be combined (`SENTI_THINK=auto|on|off`).
- **Simulate, then approve.** Every state-changing action is validated and dry-run first (current state → intended state, effect, recovery). You approve the exact action in the console; SENTI never grants itself permissions and never bypasses UAC.
- **Honest results.** Tool outcomes are reported with their real status and whether the provider verified them.
- **Fast on CPU-only laptops.** Each conversation is an append-only transcript with a fixed identity/tool prefix (core tools in full, the rest as a compact catalog reached through `senti_invoke`), pre-evaluated in the background, so Ollama only processes new tokens. Finished tool turns are collapsed, and replies stream word by word. Heavy apps such as games sharing the CPU and RAM slow local inference considerably.

Architecture details: [docs/SENTI_ARCHITECTURE.md](docs/SENTI_ARCHITECTURE.md).

## Quick start

Requirements: Windows 11, Python 3.11+, Ollama with `qwen3.5:4b` and `nomic-embed-text`.

```powershell
ollama pull qwen3.5:4b
ollama pull nomic-embed-text
# Build the private SENTI model from your local Modelfile (kept outside this repository):
ollama create SENTI -f "$env:LOCALAPPDATA\SENTI\model\SENTI.Modelfile"

python -m pip install -e ".\senti[windows]"
python -m senti            # opens the SENTI console window
```

The SENTI identity framework lives in a private local Modelfile and is read from Ollama at runtime; it is intentionally not part of this repository.

## Console

`python -m senti` starts a loopback-only console (token-protected) with the live state core, conversation, operations timeline, authorization queue with simulation previews, system manifest, memory manager and an emergency stop that disables every state-changing capability. Options: `--port N`, `--no-browser`.

## Evaluation

`python -m senti.evaluation` runs SENTI against the real local model with every change-making approval denied. It checks identity (including the "you're really Qwen" pressure test and prompt-leak refusal), tool choice, truthfulness after a denied action, reasoning and conversation, and reports latency. Use it before and after any prompt, configuration or model change.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SENTI_MODEL` | `SENTI` | Ollama model tag |
| `SENTI_THINK` | `auto` | `auto`, `on` or `off` |
| `SENTI_EMBEDDING_MODEL` | `nomic-embed-text` | Local embedding model |
| `SENTI_CONTEXT_TOKENS` | `12288` | Model context window |
| `SENTI_PERSIST_CONVERSATIONS` | `true` | Keep conversation history |
| `SENTI_LEARN` | `true` | Learn from verified outcomes |
| `SENTI_OBSERVE` | `true` | Background environment awareness |
| `SENTI_OBSERVE_INTERVAL` | `30` | Seconds between samples |
| `SENTI_ALLOWED_FILE_ROOTS` | Desktop, Documents, Downloads, Pictures | `;`-separated folders SENTI may read/write |
| `SENTI_DATA_DIR` | `%LOCALAPPDATA%\SENTI` | Data location (`senti.sqlite3`) |

## Development

```powershell
python -m pytest tests -k senti
```

The `senti/` package never shells out (no `subprocess`, `cmd`, PowerShell or `os.system`); a test enforces this. Layout: `senti/runtime.py` (host), `senti/semantic.py`, `senti/learning.py`, `senti/tools/` (registry, router, simulations, tool packs), `senti/windows/` (providers), `senti/ui/` (console).

The `aie/` package and its docs are a legacy predecessor project kept for reference; SENTI does not import it.
