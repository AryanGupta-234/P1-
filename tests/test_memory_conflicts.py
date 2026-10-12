import pytest

from aie.memory.conflicts import generate_conflict_proposals
from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore


def test_conflict_review_finds_explicit_opposing_preferences(tmp_path):
    store = MemoryStore(tmp_path / "conflicts.sqlite3")
    first = store.save(
        MemoryRecord(
            kind="semantic",
            content="Always use local inference for desktop reasoning.",
            tags=["model", "privacy"],
        )
    )
    second = store.save(
        MemoryRecord(
            kind="semantic",
            content="Never use local inference for desktop reasoning.",
            tags=["model", "privacy"],
        )
    )

    proposals = generate_conflict_proposals(store)

    assert len(proposals) == 1
    assert set(proposals[0].memory_ids) == {first.memory_id, second.memory_id}
    assert proposals[0].opposing_terms == ("always", "never")
    assert {"local", "inference", "desktop", "reasoning"}.issubset(
        set(proposals[0].shared_context_tokens)
    )
    assert proposals[0].recommended_action == "review_manually"


def test_conflict_review_requires_shared_context_and_same_kind(tmp_path):
    store = MemoryStore(tmp_path / "conflicts-context.sqlite3")
    store.save(
        MemoryRecord(kind="semantic", content="Always enable Bluetooth.")
    )
    store.save(
        MemoryRecord(kind="semantic", content="Never disable notifications.")
    )
    store.save(
        MemoryRecord(kind="episodic", content="Never enable Bluetooth.")
    )

    assert generate_conflict_proposals(store) == ()


def test_sensitive_memories_are_excluded_unless_explicitly_requested(tmp_path):
    store = MemoryStore(tmp_path / "conflicts-sensitive.sqlite3")
    store.save(
        MemoryRecord(
            kind="semantic",
            content="Always use local inference for this private workflow.",
            sensitivity="sensitive",
        )
    )
    store.save(
        MemoryRecord(
            kind="semantic",
            content="Never use local inference for this private workflow.",
            sensitivity="sensitive",
        )
    )

    assert generate_conflict_proposals(store) == ()
    assert len(generate_conflict_proposals(store, include_sensitive=True)) == 1


def test_conflict_review_respects_bounds(tmp_path):
    store = MemoryStore(tmp_path / "conflicts-bounds.sqlite3")
    with pytest.raises(ValueError, match="max_memories"):
        generate_conflict_proposals(store, max_memories=0)
    with pytest.raises(ValueError, match="minimum_shared_tokens"):
        generate_conflict_proposals(store, minimum_shared_tokens=0)
