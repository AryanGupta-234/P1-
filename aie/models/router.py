"""Hardware-aware local model routing."""
from __future__ import annotations

from aie.hardware import runtime_profile
from aie.model_policy import choose_local_model
from aie.models.base import ModelRequest, ModelResponse
from aie.models.ollama import OllamaClient, OllamaError


class ModelRoutingError(RuntimeError):
    """No eligible model is available for the requested task."""


class LocalModelRouter:
    """Route requests only to preinstalled models using current RAM headroom."""

    def __init__(self, provider: OllamaClient) -> None:
        self.provider = provider

    def generate(self, request: ModelRequest) -> ModelResponse:
        try:
            installed = self.provider.list_models()
        except OllamaError as exc:
            raise ModelRoutingError(str(exc)) from exc

        memory = runtime_profile()["memory_available_gib"]
        decision = choose_local_model(request.task, installed, memory)
        if not decision.available or decision.selected_model is None:
            raise ModelRoutingError(
                f"{decision.reason} Available memory: {decision.available_memory_gib:.2f} GiB."
            )
        try:
            return self.provider.chat(request, model=decision.selected_model)
        except OllamaError as exc:
            raise ModelRoutingError(str(exc)) from exc
