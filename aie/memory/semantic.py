"""Local Ollama-backed memory embedding index; explicit and download-free."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aie.memory.store import MemoryStore


class EmbeddingProvider(Protocol):
    def embed(
        self,
        inputs: list[str],
        *,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> list[list[float]]:
        """Return one local embedding for each input."""
        ...


@dataclass(frozen=True, slots=True)
class MemoryIndexReport:
    model: str
    eligible_memories: int
    already_indexed: int
    indexed_now: int


def index_memory_embeddings(
    store: MemoryStore,
    provider: EmbeddingProvider,
    *,
    model: str,
    batch_size: int = 8,
    include_sensitive: bool = False,
) -> MemoryIndexReport:
    """Index active, non-expired memories with an already-installed local model."""
    if not isinstance(model, str) or not model.strip() or len(model) > 120:
        raise ValueError("embedding model must be a non-empty name up to 120 characters")
    if not 1 <= batch_size <= 32:
        raise ValueError("batch_size must be between 1 and 32")

    memories = store.list_memories(
        include_sensitive=include_sensitive,
        limit=1000,
    )
    existing = [
        item for item in memories
        if store.has_embedding(item.memory.memory_id, model)
    ]
    pending = [
        item for item in memories
        if not store.has_embedding(item.memory.memory_id, model)
    ]

    indexed = 0
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        inputs = [
            memory.memory.content
            + ("\nTags: " + ", ".join(memory.memory.tags) if memory.memory.tags else "")
            for memory in batch
        ]
        vectors = provider.embed(inputs, model=model)
        if len(vectors) != len(batch):
            raise ValueError("embedding provider returned a different number of vectors")
        for item, vector in zip(batch, vectors, strict=True):
            store.save_embedding(item.memory.memory_id, model, vector)
            indexed += 1

    return MemoryIndexReport(
        model=model,
        eligible_memories=len(memories),
        already_indexed=len(existing),
        indexed_now=indexed,
    )
