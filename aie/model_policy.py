"""Conservative local Ollama discovery and hardware-aware model selection."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.error import URLError
from urllib.request import Request, urlopen

import psutil

TaskKind = Literal["routine", "complex", "embedding"]
DEFAULT_ROUTINE = "qwen2.5:3b-instruct"
DEFAULT_COMPLEX = "qwen2.5:7b-instruct"
DEFAULT_EMBEDDING = "nomic-embed-text:latest"
COMPLEX_MIN_AVAILABLE_GIB = 7.5


@dataclass(frozen=True)
class ModelDecision:
    task: str
    selected_model: str | None
    available: bool
    reason: str
    available_memory_gib: float


def ollama_base_url() -> str:
    return os.environ.get("AIE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def discover_local_models(timeout: float = 1.5) -> list[str]:
    """Query only the local Ollama endpoint. Never pulls or contacts a cloud service."""
    request = Request(f"{ollama_base_url()}/api/tags", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return []
    models = payload.get("models", []) if isinstance(payload, dict) else []
    return sorted({
        str(item.get("name"))
        for item in models
        if isinstance(item, dict) and item.get("name")
    })


def choose_local_model(
    task: TaskKind,
    installed_models: set[str] | list[str],
    available_memory_gib: float | None = None,
) -> ModelDecision:
    """Choose an already-installed local model; no implicit downloads or cloud fallback."""
    installed = set(installed_models)
    if available_memory_gib is None:
        available_memory_gib = psutil.virtual_memory().available / (1024 ** 3)
    available_memory_gib = max(0.0, float(available_memory_gib))

    if task == "embedding":
        selected = DEFAULT_EMBEDDING if DEFAULT_EMBEDDING in installed else None
        reason = "Dedicated local embedding model." if selected else "Embedding model is not installed."
    elif task == "routine":
        selected = DEFAULT_ROUTINE if DEFAULT_ROUTINE in installed else None
        reason = "Default lightweight local reasoning model." if selected else (
            "Routine local model is not installed; refusing an implicit model download."
        )
    elif task == "complex":
        if DEFAULT_COMPLEX in installed and available_memory_gib >= COMPLEX_MIN_AVAILABLE_GIB:
            selected = DEFAULT_COMPLEX
            reason = "Complex task and sufficient currently available memory."
        elif DEFAULT_ROUTINE in installed:
            selected = DEFAULT_ROUTINE
            reason = (
                "Memory guard kept inference on the 3B model."
                if DEFAULT_COMPLEX in installed
                else "7B model is unavailable; using the installed 3B model."
            )
        else:
            selected = None
            reason = "No eligible local reasoning model is installed."
    else:
        raise ValueError(f"Unsupported task kind: {task}")

    return ModelDecision(
        task=task,
        selected_model=selected,
        available=selected is not None,
        reason=reason,
        available_memory_gib=round(available_memory_gib, 2),
    )


def decision_dict(decision: ModelDecision) -> dict:
    return asdict(decision)
