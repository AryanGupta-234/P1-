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


@dataclass(frozen=True, slots=True)
class SentiSettings:
    """Immutable host settings. Normal inference is deliberately non-thinking."""

    model: str = "SENTI"
    operator_name: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    request_timeout_seconds: float = 90.0
    max_tool_rounds: int = 3
    max_tool_result_chars: int = 8_000
    context_messages: int = 20
    max_output_tokens: int = 700
    temperature: float = 0.25
    think: bool = False
    auto_start_ollama: bool = True
    persist_conversations: bool = False
    include_window_titles: bool = False

    @classmethod
    def from_env(cls) -> "SentiSettings":
        """Load only bounded runtime configuration; THINK is intentionally not env-overridable."""
        return cls(
            model=os.environ.get("SENTI_MODEL", "SENTI"),
            operator_name=(os.environ.get("SENTI_OPERATOR_NAME", "").strip() or None),
            ollama_base_url=os.environ.get("SENTI_OLLAMA_URL", "http://127.0.0.1:11434"),
            request_timeout_seconds=float(os.environ.get("SENTI_REQUEST_TIMEOUT", "90")),
            max_tool_rounds=int(os.environ.get("SENTI_MAX_TOOL_ROUNDS", "3")),
            max_tool_result_chars=int(os.environ.get("SENTI_MAX_TOOL_RESULT_CHARS", "8000")),
            context_messages=int(os.environ.get("SENTI_CONTEXT_MESSAGES", "20")),
            max_output_tokens=int(os.environ.get("SENTI_MAX_OUTPUT_TOKENS", "700")),
            temperature=float(os.environ.get("SENTI_TEMPERATURE", "0.25")),
            think=False,
            auto_start_ollama=os.environ.get("SENTI_AUTO_START_OLLAMA", "true").strip().lower() in {"1", "true", "yes"},
            persist_conversations=os.environ.get("SENTI_PERSIST_CONVERSATIONS", "false").strip().lower() in {"1", "true", "yes"},
            include_window_titles=os.environ.get("SENTI_INCLUDE_WINDOW_TITLES", "false").strip().lower() in {"1", "true", "yes"},
        )

    def validate(self) -> None:
        if not self.model or len(self.model) > 128:
            raise ValueError("SENTI model tag must contain 1 to 128 characters")
        if not 1 <= self.request_timeout_seconds <= 300:
            raise ValueError("request timeout must be between 1 and 300 seconds")
        if not 1 <= self.max_tool_rounds <= 3:
            raise ValueError("max_tool_rounds must be between 1 and 3")
        if not 512 <= self.max_tool_result_chars <= 32_000:
            raise ValueError("max_tool_result_chars must be between 512 and 32000")
        if not 1 <= self.context_messages <= 32:
            raise ValueError("context_messages must be between 1 and 32")
        if not 32 <= self.max_output_tokens <= 4096:
            raise ValueError("max_output_tokens must be between 32 and 4096")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.think is not False:
            raise ValueError("SENTI normal inference must keep think=False in the Python runtime")
