SENTINEL - always-on Windows gaming performance guardian

INSTALL   : double-click install.bat (accept the admin prompt). Starts at interactive user logon; restart-on-failure enabled.
OPEN HUD  : desktop shortcut "SENTINEL", any time, even mid-game. Local only (127.0.0.1).
TRY IT    : python agent.py --demo   (synthetic data, any OS)
UNINSTALL : uninstall.bat

Watches continuously (all visible in the ACTIVITY tab): CPU and cores, RAM and paging, DPC and
interrupt time, disk latency, NVIDIA GPU, ping and jitter, process spawn/exit, outbound connections,
services, startup entries, Windows event logs, power plan, VBS, Defender, Vanguard state.
It names the cause of each lag spike, can record ETW kernel traces (Windows Performance Recorder),
looks up Microsoft Learn + GitHub for the issue, and has two Ollama models (fast + deep) verify it.
Actions are allowlisted and approval-gated by default. A reviewed visible GUI app may receive WM_CLOSE after two explicit confirmations; SENTINEL never force-kills it. Other allowlisted actions are shown in CONTROL.

AI: install Ollama, then:  ollama pull qwen3:4b   and   ollama pull qwen3:8b
    (or paste a free Groq key in CONTROL > AI settings to use a free cloud model for the deep role)
Data/config: %ProgramData%\Sentinel (SQLite is durable; config.json is the protected recovery mirror)
Not a kernel driver: live DPC/paging values are Windows PDH performance counters. WPR/ETW is queried and captured separately; captured ETL files can be opened in Windows Performance Analyzer. SENTINEL does not decode live DWM frame pacing or claim real-time GUI FPS.

UI v2 (P1 skin): steel-blue P1 palette, rounded cards, grouped sidebar, boot splash tied to real load steps,
Ctrl+K command palette (screens + allowlisted actions), toast feedback, desktop alerts for serious lag,
process/connection filters, activity log export, keys 1-8 switch screens, last screen remembered.

UI v3: original P1 black/charcoal + orange + lime theme. New screens: SYSTEM (inventory explorer, security posture, storage), EVIDENCE (searchable vault + CSV), TASKS (agent jobs, action history, dispatch). Command metric cards.

UI v4: FEATURES screen (automation master switch, per-sensor toggles, intervals/thresholds, presets, audit timeline). Settings apply live to the collectors; saved in config.json under "profile".

UI v5: additive INTELLIGENCE workspace. Evidence-linked environment state with bounded
provenance references and explainable recency ranking; explicit local memory with revisions,
sensitivity controls and optional local semantic search; dependency-aware goals and reviewed
local plan drafts; RAM-aware DEEP-model fallback; and an explicitly triggered, read-only
Windows UI Automation structural inspector. Existing SENTINEL screens, collectors, action
allowlist, approval queue and P1 color theme are retained. See INTELLIGENCE_INTEGRATION.md
for capability comparison, privacy boundaries, API routes and Windows-session limitation.