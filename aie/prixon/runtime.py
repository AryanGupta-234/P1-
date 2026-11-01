"""PRIXON request runtime built on AIE's existing provider/router contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from aie.models.base import ChatMessage, ModelRequest, ModelResponse
from aie.prixon.context import ContextReference, append_references_to_prompt, retrieve_context
from aie.prixon.identity import (\n    DEFAULT_PRIXON_IDENTITY,\n    PRIXONIdentity,\n    apply_prixon_identity,\n)


class ModelGenerator(Protocol):
    """Existing AIE router/provider surface required by PRIXON."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a response through the configured, policy-aware model router."""
        ...


@dataclass(frozen=True, slots=True)
class PRIXONTurn:
    """One PRIXON response plus the exact references attached to that turn."""

    identity: str
    release: str
    response: ModelResponse
    references: tuple[ContextReference, ...]


class PRIXONRuntime:
    """PRIXON identity and context layer over AIE's existing intelligence engines.

    The runtime does not replace Ollama, the provider contracts, MemoryStore,
    KnowledgeStore, task orchestration, or the policy broker.
    """

    def __init__(
        self,
        model_router: ModelGenerator,
        *,
        memory_store: Any | None = None,
        knowledge_store: Any | None = None,
        identity: PRIXONIdentity = DEFAULT_PRIXON_IDENTITY,
    ) -> None:
        if not callable(getattr(model_router, "generate", None)):
            raise TypeError("model_router must expose generate(ModelRequest)")
        self.model_router = model_router
        self.memory_store = memory_store
        self.knowledge_store = knowledge_store
        self.identity = identity

    def generate(
        self,
        prompt: str,
        *,
        task: Literal["routine", "complex"] = "routine",
        include_memory: bool = False,
        include_knowledge: bool = False,
        max_context_items: int = 6,
        max_output_tokens: int = 512,
    ) -> PRIXONTurn:
        """Generate one response; context attachment is opt-in on every turn."""
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12_000:
            raise ValueError("prompt must contain 1..12000 non-whitespace characters")
        references = retrieve_context(
            prompt,
            memory_store=self.memory_store,
            knowledge_store=self.knowledge_store,
            include_memory=include_memory,
            include_knowledge=include_knowledge,
            limit=max_context_items,
        )
        user_content = append_references_to_prompt(prompt.strip(), references)
        messages = apply_prixon_identity(
            [ChatMessage(role="user", content=user_content)],
            self.identity,
        )
        request = ModelRequest(
            task=task,
            messages=messages,
            max_output_tokens=max_output_tokens,
        )
        response = self.model_router.generate(request)
        return PRIXONTurn(
            identity=self.identity.name,
            release=self.identity.release,
            response=response,
            references=references,
        )
