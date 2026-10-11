"""Model-provider abstractions and local-first routing."""
from aie.models.base import ChatMessage, ModelRequest, ModelResponse
from aie.models.openai_compatible import (
    CloudEgressDenied,
    CloudModelError,
    CloudModelUnavailable,
    OpenAICompatibleClient,
)
from aie.models.ollama import OllamaClient, OllamaError, OllamaUnavailable
from aie.models.router import LocalModelRouter, ModelRoutingError

__all__ = [
    "ChatMessage",
    "CloudEgressDenied",
    "CloudModelError",
    "CloudModelUnavailable",
    "OpenAICompatibleClient",
    "ModelRequest",
    "ModelResponse",
    "OllamaClient",
    "OllamaError",
    "OllamaUnavailable",
    "LocalModelRouter",
    "ModelRoutingError",
]
