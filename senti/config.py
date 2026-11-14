"""Configuration for the standalone SENTI runtime (no AIE path dependency)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def senti_data_dir() -> Path:
    """Return SENTI's own per-user data directory."""
    override = os.environ.get("SENTI_DATA_DIR")
    if override:
        root = Path(override).expanduser()
    elif os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "SENTI"
    elif os.name == "nt":
        root = Path.home() / "AppData" / "Local" / "SENTI"
    else:
        # Non-Windows fallback exists only so contract/unit tests can run cross-platform.
        root = Path.home() / ".local" / "share" / "SENTI"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class SentiSettings:
    """Immutable host settings.

    ``think_mode`` controls deliberate reasoning:
    - ``auto`` (default): the host turns thinking on for planning/diagnosis rounds and for
      interpreting failed tool results, and keeps plain conversation fast.
    - ``off``: never think. ``on``: always think (slow on CPU-only machines).
    """

    model: str = "SENTI"
    operator_name: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    request_timeout_seconds: float = 300.0
    max_tool_rounds: int = 6
    max_tool_result_chars: int = 8_000
    context_messages: int = 20
    context_tokens: int = 12_288
    max_output_tokens: int = 900
    max_thinking_output_tokens: int = 2_400
    temperature: float = 0.25
    think_mode: str = "auto"
    embedding_model: str = "nomic-embed-text"
    auto_start_ollama: bool = True
    persist_conversations: bool = True
    learn_from_outcomes: bool = True
    include_window_titles: bool = False
    observe_environment: bool = True
    observe_interval_seconds: float = 30.0

    @property
    def think(self) -> bool:
        """Backward-compatible view: True only when thinking is forced on."""
        return self.think_mode == "on"

    @classmethod
    def from_env(cls) -> "SentiSettings":
        """Load bounded runtime configuration from SENTI_* environment variables."""
        return cls(
            model=os.environ.get("SENTI_MODEL", "SENTI"),
            operator_name=(os.environ.get("SENTI_OPERATOR_NAME", "").strip() or None),
            ollama_base_url=os.environ.get("SENTI_OLLAMA_URL", "http://127.0.0.1:11434"),
            request_timeout_seconds=float(os.environ.get("SENTI_REQUEST_TIMEOUT", "300")),
            max_tool_rounds=int(os.environ.get("SENTI_MAX_TOOL_ROUNDS", "6")),
            max_tool_result_chars=int(os.environ.get("SENTI_MAX_TOOL_RESULT_CHARS", "8000")),
            context_messages=int(os.environ.get("SENTI_CONTEXT_MESSAGES", "20")),
            context_tokens=int(os.environ.get("SENTI_CONTEXT_TOKENS", "12288")),
            max_output_tokens=int(os.environ.get("SENTI_MAX_OUTPUT_TOKENS", "900")),
            max_thinking_output_tokens=int(os.environ.get("SENTI_MAX_THINKING_TOKENS", "2400")),
            temperature=float(os.environ.get("SENTI_TEMPERATURE", "0.25")),
            think_mode=os.environ.get("SENTI_THINK", "auto").strip().lower(),
            embedding_model=os.environ.get("SENTI_EMBEDDING_MODEL", "nomic-embed-text"),
            auto_start_ollama=_flag("SENTI_AUTO_START_OLLAMA", "true"),
            persist_conversations=_flag("SENTI_PERSIST_CONVERSATIONS", "true"),
            learn_from_outcomes=_flag("SENTI_LEARN", "true"),
            include_window_titles=_flag("SENTI_INCLUDE_WINDOW_TITLES", "false"),
            observe_environment=_flag("SENTI_OBSERVE", "true"),
            observe_interval_seconds=float(os.environ.get("SENTI_OBSERVE_INTERVAL", "30")),
        )

    def validate(self) -> None:
        if not self.model or len(self.model) > 128:
            raise ValueError("SENTI model tag must contain 1 to 128 characters")
        if not 1 <= self.request_timeout_seconds <= 300:
            raise ValueError("request timeout must be between 1 and 300 seconds")
        if not 1 <= self.max_tool_rounds <= 8:
            raise ValueError("max_tool_rounds must be between 1 and 8")
        if not 512 <= self.max_tool_result_chars <= 32_000:
            raise ValueError("max_tool_result_chars must be between 512 and 32000")
        if not 1 <= self.context_messages <= 32:
            raise ValueError("context_messages must be between 1 and 32")
        if not 2_048 <= self.context_tokens <= 131_072:
            raise ValueError("context_tokens must be between 2048 and 131072")
        if not 32 <= self.max_output_tokens <= 4096:
            raise ValueError("max_output_tokens must be between 32 and 4096")
        if not 256 <= self.max_thinking_output_tokens <= 8192:
            raise ValueError("max_thinking_output_tokens must be between 256 and 8192")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.think_mode not in {"auto", "on", "off"}:
            raise ValueError("think_mode must be auto, on or off")
        if not 5 <= self.observe_interval_seconds <= 3600:
            raise ValueError("observe_interval_seconds must be between 5 and 3600")
        if not self.embedding_model or len(self.embedding_model) > 128:
            raise ValueError("embedding model tag must contain 1 to 128 characters")
