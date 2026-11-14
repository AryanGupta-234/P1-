"""Lifecycle wrapper used by the SENTI desktop console and other embedders."""
from __future__ import annotations

from senti.events import EventSink
from senti.runtime import SentiHost
from senti.tools.registry import ApprovalHandler


class SentiService:
    """In-process facade. The future desktop UI can provide an explicit approval callback."""

    def __init__(self, host: SentiHost | None = None, *,
                 approval_handler: ApprovalHandler | None = None,
                 event_sink: EventSink | None = None):
        self.host = host or SentiHost(approval_handler=approval_handler, event_sink=event_sink)
        self._started = False

    def start(self, *, warm_up: bool = True) -> dict:
        self.host.ensure_model_provider()
        manifest = self.host.runtime_manifest()
        self._started = True
        start_monitor = getattr(self.host, "start_environment_monitor", None)
        if callable(start_monitor):
            start_monitor()
        if warm_up and manifest.get("model_installed"):
            import threading
            threading.Thread(target=self.host.warm_up, name="senti-warmup", daemon=True).start()
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
        environment = getattr(self.host, "environment", None)
        if environment is not None:
            environment.stop()
