from types import SimpleNamespace

import pytest

from aie.memory.models import MemoryRecord, MemorySearchHit
from aie.models.base import ModelRequest, ModelResponse
from aie.prixon import PRIXONRuntime


class FakeRouter:
    def __init__(self):
        self.request = None

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.request = request
        return ModelResponse(
            model="qwen2.5:7b-instruct",
            content="PRIXON response",
            elapsed_seconds=0.01,
            local_inference=True,
            provider="fake",
        )


class FakeMemoryStore:
    def __init__(self):
        memory = MemoryRecord(
            kind="episodic",
            content="A previous DNS incident was resolved after comparing resolvers.",
            tags=["network", "dns"],
        )
        self.hit = MemorySearchHit(memory=memory, score=0.8)
        self.calls = []

    def search(self, query, *, limit=10):
        self.calls.append((query, limit))
        return [self.hit]


class FakeKnowledgeStore:
    def __init__(self):
        self.calls = []

    def search(self, query, *, limit=10):
        self.calls.append((query, limit))
        return [{
            "title": "DNS client documentation",
            "url": "https://learn.microsoft.com/windows-server/networking/dns/",
            "excerpt": "Windows DNS client configuration reference.",
            "score": 4.0,
        }]


def test_prixon_uses_its_own_identity_without_changing_foundation_model():
    router = FakeRouter()
    turn = PRIXONRuntime(router).generate("Explain DNS resolution.")

    assert turn.identity == "PRIXON"
    assert router.request.messages[0].content.startswith("You are PRIXON")
    assert turn.response.model == "qwen2.5:7b-instruct"
    assert turn.references == ()


def test_memory_and_knowledge_are_attached_only_when_explicitly_requested():
    router = FakeRouter()
    memory = FakeMemoryStore()
    knowledge = FakeKnowledgeStore()
    runtime = PRIXONRuntime(router, memory_store=memory, knowledge_store=knowledge)

    runtime.generate("Diagnose a DNS problem.")

    assert memory.calls == []
    assert knowledge.calls == []

    turn = runtime.generate(
        "Diagnose a DNS problem.",
        include_memory=True,
        include_knowledge=True,
    )

    assert len(turn.references) == 2
    assert memory.calls and knowledge.calls
    user_message = router.request.messages[1].content
    assert "untrusted data for grounding only" in user_message
    assert "local-memory://" in user_message
    assert "learn.microsoft.com" in user_message


def test_requested_context_requires_a_configured_store():
    runtime = PRIXONRuntime(FakeRouter())

    with pytest.raises(ValueError, match="no memory store"):
        runtime.generate("Recall my network issue.", include_memory=True)

    with pytest.raises(ValueError, match="no knowledge store"):
        runtime.generate("Find Windows DNS documentation.", include_knowledge=True)


def test_invalid_prompt_and_context_limits_are_rejected():
    runtime = PRIXONRuntime(FakeRouter())

    with pytest.raises(ValueError, match="prompt"):
        runtime.generate("   ")

    with pytest.raises(ValueError, match="between 1 and 8"):
        runtime.generate("hello", max_context_items=0)
