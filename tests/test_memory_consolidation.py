from aie.memory.consolidation import generate_consolidation_proposals
from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore


def test_consolidation_finds_reviewable_duplicate_candidates(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    first = store.save(MemoryRecord(
        kind="semantic",
        content="Use the local Ollama model for private reasoning tasks.",
        tags=["model", "local"],
    ))
    second = store.save(MemoryRecord(
        kind="semantic",
        content="Use the local Ollama model for private reasoning work.",
        tags=["model", "local"],
    ))

    proposals = generate_consolidation_proposals(store)

    assert proposals
    assert proposals[0].memory_ids == (second.memory_id, first.memory_id) or proposals[0].memory_ids == (first.memory_id, second.memory_id)
    assert proposals[0].recommended_action == "review_manually"
    assert proposals[0].similarity >= 0.82
    assert store.count() == 2


def test_consolidation_does_not_cross_memory_kinds(tmp_path):
    store = MemoryStore(tmp_path / "memory-kinds.sqlite3")
    store.save(MemoryRecord(
        kind="semantic",
        content="Review Windows event logs before changing settings.",
    ))
    store.save(MemoryRecord(
        kind="procedural",
        content="Review Windows event logs before changing settings.",
    ))

    assert generate_consolidation_proposals(store) == ()


def test_sensitive_memories_stay_excluded_by_default(tmp_path):
    store = MemoryStore(tmp_path / "memory-sensitive.sqlite3")
    store.save(MemoryRecord(
        kind="semantic",
        content="Private account recovery information.",
        sensitivity="sensitive",
    ))
    store.save(MemoryRecord(
        kind="semantic",
        content="Private account recovery information.",
        sensitivity="internal",
    ))

    assert generate_consolidation_proposals(store) == ()
    assert generate_consolidation_proposals(store, include_sensitive=True)


def test_consolidation_is_bounded(tmp_path):
    store = MemoryStore(tmp_path / "memory-bounded.sqlite3")
    for index in range(8):
        store.save(MemoryRecord(
            kind="semantic",
            content=f"Same repeated operational memory about local model routing {index}.",
            tags=["model"],
        ))

    proposals = generate_consolidation_proposals(
        store,
        max_memories=5,
        max_proposals=2,
    )
    assert len(proposals) <= 2
