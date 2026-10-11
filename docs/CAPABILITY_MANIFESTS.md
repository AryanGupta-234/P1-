# User-Managed Capability Manifests

P1- loads capability definitions only from `%LOCALAPPDATA%\AIE\capabilities\*.json`. The folder is empty by default. An absent or invalid manifest never grants permissions; invalid files cause the loader to fail closed.

Example manifest (save as `open-settings.json`):

```json
{
  "capability_id": "windows.open_settings",
  "description": "Open a named Windows Settings page.",
  "risk_tier": "low",
  "enabled": true,
  "allow_autonomous": false,
  "approval_required": true,
  "allowed_parameters": ["settings_page"],
  "max_invocations_per_minute": 3,
  "max_execution_seconds": 5
}
```

The manifest declares a policy boundary; it does not install or enable an executor. In this phase, all queued proposals wait for explicit review even if the manifest says a low-risk capability may be autonomous. Approving a proposal stores a policy authorization record only. No Windows command, process, API or UI action is executed.

Available CLI:

- `aie capabilities` — list loaded manifests
- `aie propose windows.open_settings "Open display settings" --parameters '{"settings_page":"display"}'`
- `aie proposals` — list pending review
- `aie approve-proposal <proposal-id>` / `aie reject-proposal <proposal-id>`
- `aie proposal-audit <proposal-id>` — inspect the review event history

Parameter payloads must be flat JSON objects with at most 20 scalar entries or scalar lists, bounded to 8 KiB. Nested objects and keys that look like credentials/tokens are rejected. Do not place secrets in summary text or proposal data.

The SQLite ledger is append-only through the AIE application API and lives in a separate `policy-audit.sqlite3` database. Each event is linked to the previous event with a SHA-256 hash; run `aie policy-audit-check` to detect payload edits, row deletion or chain breaks. This is tamper-evident, not tamper-proof against an administrator who can rewrite both data and hashes.