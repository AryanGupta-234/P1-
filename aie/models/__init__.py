"""Model-provider abstractions and local-first routing."""
from aie.models.base import ChatMessage, ModelRequest, ModelResponse
from aie.models.ollama import OllamaClient, OllamaError, OllamaUnavailable
from aie.models.router import LocalModelRouter, ModelRoutingError

__all__ = [
    "ChatMessage",
    "ModelRequest",
    "ModelResponse",
    "OllamaClient",
    "OllamaError",
    "OllamaUnavailable",
    "LocalModelRouter",
    "ModelRoutingError",
]
