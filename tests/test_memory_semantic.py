from datetime import datetime, timedelta, timezone

import pytest

from aie.memory.models import MemoryRecord
from aie.memory.semantic import index_memory_embeddings
from aie.memory.store import MemoryStore


class FakeEmbeddingProvider:
    def __init__(self):
        self.calls = []

    def embed(self, inputs, *, model, timeout_seconds=60.0):
        self.calls.append((list(inputs), model, timeout_seconds))
        vectors = []
        for text in inputs:
            lower = text.lower()
            if "browser" in lower or "edge" in lower:
                vectors.append([1.0, 0.0, 0.0])
            elif "network" in lower or "dns" in lower:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def test_semantic_memory_search_ranks_by_cosine_similarity(tmp_path):
    store = MemoryStore(tmp_path / "semantic-search.sqlite3")
    browser = store.save(MemoryRecord(
        kind="semantic",
        content="Browser playback and Edge video stalls.",
    ))
    store.save_embedding(browser.memory_id, "nomic-embed-text", [1.0, 0.0, 0.0])
    network = store.save(MemoryRecord(
        kind="episodic",
        content="DNS resolution and network latency.",
    ))
    store.save_embedding(network.memory_id, "nomic-embed-text", [0.0, 1.0, 0.0])

    hits = store.search_semantic(
        [0.9, 0.1, 0.0],
        model="nomic-embed-text",
    )

    assert hits[0].memory.memory_id == browser.memory_id
    assert hits[0].score > hits[1].score
    assert 0.0 <= hits[0].score <= 2.0


def test_semantic_search_keeps_sensitive_memories_private_by_default(tmp_path):
    store = MemoryStore(tmp_path / "semantic-sensitive.sqlite3")
    secret = store.save(MemoryRecord(
        kind="episodic",
        content="Sensitive recovery memory.",
        sensitivity="sensitive",
    ))
    store.save_embedding(secret.memory_id, "nomic-embed-text", [1.0, 0.0])

    assert store.search_semantic(
        [1.0, 0.0],
        model="nomic-embed-text",
    ) == []
    visible = store.search_semantic(
        [1.0, 0.0],
        model="nomic-embed-text",
        include_sensitive=True,
    )
    assert visible[0].memory.memory_id == secret.memory_id


def test_semantic_index_skips_existing_vectors_and_never_indexes_sensitive_by_default(tmp_path):
    store = MemoryStore(tmp_path / "semantic-index.sqlite3")
    first = store.save(MemoryRecord(kind="semantic", content="Browser video playback."))
    store.save_embedding(first.memory_id, "nomic-embed-text", [1.0, 0.0, 0.0])
    second = store.save(MemoryRecord(kind="episodic", content="Network DNS resolution."))
    store.save(MemoryRecord(
        kind="episodic",
        content="Private recovery content.",
        sensitivity="sensitive",
    ))
    provider = FakeEmbeddingProvider()

    report = index_memory_embeddings(
        store,
        provider,
        model="nomic-embed-text",
        batch_size=2,
    )

    assert report.eligible_memories == 2
    assert report.already_indexed == 1
    assert report.indexed_now == 1
    assert len(provider.calls) == 1
    assert store.has_embedding(second.memory_id, "nomic-embed-text")
    assert not any("Private" in text for batch, _, _ in provider.calls for text in batch)


def test_semantic_index_can_include_sensitive_only_when_explicit(tmp_path):
    store = MemoryStore(tmp_path / "semantic-include-sensitive.sqlite3")
    secret = store.save(MemoryRecord(
        kind="episodic",
        content="Sensitive private details.",
        sensitivity="sensitive",
    ))
    report = index_memory_embeddings(
        store,
        FakeEmbeddingProvider(),
        model="nomic-embed-text",
        include_sensitive=True,
    )
    assert report.indexed_now == 1
    assert store.has_embedding(secret.memory_id, "nomic-embed-text")


def test_delete_and_expiry_prune_remove_associated_vectors(tmp_path):
    store = MemoryStore(tmp_path / "semantic-delete.sqlite3")
    memory = store.save(MemoryRecord(kind="semantic", content="To be deleted."))
    store.save_embedding(memory.memory_id, "nomic-embed-text", [1.0, 0.0])

    assert store.delete(memory.memory_id) is True
    assert store.has_embedding(memory.memory_id, "nomic-embed-text") is False

    now = datetime.now(timezone.utc)
    expiring = store.save(MemoryRecord(
        kind="working",
        content="Temporary vector memory.",
        created_at=now,
        expires_at=now + timedelta(minutes=1),
    ))
    store.save_embedding(expiring.memory_id, "nomic-embed-text", [0.0, 1.0])
    assert store.prune_expired(now=now + timedelta(minutes=2)) == 1
    assert store.has_embedding(expiring.memory_id, "nomic-embed-text") is False


def test_semantic_store_rejects_invalid_vectors_and_dimension_mismatch(tmp_path):
    store = MemoryStore(tmp_path / "semantic-validation.sqlite3")
    memory = store.save(MemoryRecord(kind="semantic", content="Valid memory."))

    with pytest.raises(ValueError):
        store.save_embedding(memory.memory_id, "nomic-embed-text", [0.0, 0.0])
    with pytest.raises(ValueError):
        store.search_semantic([0.0, 0.0], model="nomic-embed-text")

    store.save_embedding(memory.memory_id, "nomic-embed-text", [1.0, 0.0, 0.0])
    assert store.search_semantic([1.0, 0.0], model="nomic-embed-text") == []


def test_semantic_search_excludes_orthogonal_or_unrelated_vectors_by_threshold(tmp_path):
    store = MemoryStore(tmp_path / "semantic-threshold.sqlite3")
    relevant = store.save(MemoryRecord(kind="semantic", content="Browser context."))
    unrelated = store.save(MemoryRecord(kind="semantic", content="Network context."))
    store.save_embedding(relevant.memory_id, "embed-v1", [1.0, 0.0, 0.0])
    store.save_embedding(unrelated.memory_id, "embed-v1", [0.0, 1.0, 0.0])

    hits = store.search_semantic(
        [0.9, 0.1, 0.0],
        model="embed-v1",
        minimum_score=0.2,
    )

    assert [item.memory.memory_id for item in hits] == [relevant.memory_id]
    assert hits[0].score > 0.9


def test_semantic_search_rejects_invalid_similarity_threshold(tmp_path):
    store = MemoryStore(tmp_path / "semantic-threshold-validation.sqlite3")
    with pytest.raises(ValueError, match="minimum_score"):
        store.search_semantic([1.0, 0.0], model="embed-v1", minimum_score=1.1)
