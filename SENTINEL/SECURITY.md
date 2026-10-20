# Security notes

- The local dashboard token is an authentication secret. Do not publish tokenized URLs or runtime `config.json`.
- Keep the HTTP listener on loopback. Do not expose port 8765 to a LAN or the public internet.
- Cloud inference is disabled by default. When enabled, diagnostic context is sent to the configured API provider; inspect that provider's retention and privacy terms.
- The installer creates a `SYSTEM` scheduled task and must be reviewed before deployment.
- Automatic remediation is disabled by default. Review each allowlisted action before enabling its autopilot setting.
- Report security issues privately to the repository maintainer rather than opening a public issue containing secrets or exploit details.