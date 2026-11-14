"""Lifecycle wrapper for embedding SENTI in the future independent Windows desktop application."""
from __future__ import annotations

from senti.runtime import SentiHost
from senti.tools.registry import ApprovalHandler


class SentiService:
    """In-process facade. The future desktop UI can provide an explicit approval callback."""

    def __init__(self, host: SentiHost | None = None, *,
                 approval_handler: ApprovalHandler | None = None):
        self.host = host or SentiHost(approval_handler=approval_handler)
        self._started = False

    def start(self) -> dict:
        self.host.ensure_model_provider()
        manifest = self.host.runtime_manifest()
        self._started = True
        return manifest

    def send_message(self, message: str, *, conversation_id: str | None = None) -> dict:
        if not self._started:
            self.start()
        return self.host.chat(message, conversation_id=conversation_id)

    def set_emergency_stop(self, enabled: bool, *, reason: str = "host_operator") -> dict:
        """Expose the host-owned emergency stop to an embedding UI or service."""
        return self.host.set_emergency_stop(enabled, reason=reason)

    def stop(self) -> None:
        self._started = False
