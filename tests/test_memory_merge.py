import pytest

from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore


def test_reviewed_merge_supersedes_both_sources_and_preserves_lineage(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    first = store.save(
        MemoryRecord(
            kind="procedural",
            content="Open the application before inspecting its state.",
            tags=["desktop", "workflow"],
            confidence=0.9,
        )
    )
    second = store.save(
        MemoryRecord(
            kind="procedural",
            content="Inspect application state after opening it.",
            tags=["desktop", "inspection"],
            confidence=0.8,
        )
    )
    merged = MemoryRecord(
        kind="procedural",
        content="Open the application, then inspect its state.",
        tags=["desktop", "workflow", "inspection"],
        confidence=0.8,
    )

    result = store.merge((first.memory.memory_id, second.memory.memory_id), merged)

    assert result.memory_id != first.memory.memory_id
    assert result.memory_id != second.memory.memory_id
    assert store.get(first.memory.memory_id) is None
    assert store.get(second.memory.memory_id) is None
    assert store.get(first.memory.memory_id, include_superseded=True).status == "superseded"
    assert store.get(second.memory.memory_id, include_superseded=True).status == "superseded"
    assert set(store.lineage(result.memory_id)) == {
        first.memory.memory_id,
        second.memory.memory_id,
    }
    assert store.count(include_superseded=False) == 1
    assert store.count(include_superseded=True) == 3


def test_merge_cannot_reduce_sensitivity_or_inflate_confidence(tmp_path):
    store = MemoryStore(tmp_path / "memory-sensitive.sqlite3")
    first = store.save(
        MemoryRecord(kind="semantic", content="Sensitive fact.", sensitivity="sensitive", confidence=0.7)
    )
    second = store.save(
        MemoryRecord(kind="semantic", content="Related internal fact.", confidence=0.9)
    )

    with pytest.raises(ValueError, match="cannot reduce source sensitivity"):
        store.merge(
            (first.memory.memory_id, second.memory.memory_id),
            MemoryRecord(kind="semantic", content="Combined fact.", sensitivity="internal", confidence=0.7),
        )

    with pytest.raises(ValueError, match="cannot exceed"):
        store.merge(
            (first.memory.memory_id, second.memory.memory_id),
            MemoryRecord(kind="semantic", content="Combined fact.", sensitivity="sensitive", confidence=0.8),
        )

    assert store.count(include_superseded=False) == 2


def test_merge_preserves_earliest_expiry_and_rejects_kind_mismatch(tmp_path):
    from datetime import datetime, timedelta, timezone

    store = MemoryStore(tmp_path / "memory-expiry.sqlite3")
    now = datetime.now(timezone.utc)
    first = store.save(
        MemoryRecord(
            kind="episodic",
            content="First event summary.",
            created_at=now,
            expires_at=now + timedelta(days=2),
        )
    )
    second = store.save(
        MemoryRecord(
            kind="episodic",
            content="Second event summary.",
            created_at=now,
            expires_at=now + timedelta(days=5),
        )
    )

    with pytest.raises(ValueError, match="cannot outlive"):
        store.merge(
            (first.memory.memory_id, second.memory.memory_id),
            MemoryRecord(
                kind="episodic",
                content="Combined event summary.",
                created_at=now,
                expires_at=now + timedelta(days=3),
            ),
            now=now,
        )

    wrong_kind = MemoryRecord(kind="semantic", content="Wrong kind.")
    with pytest.raises(ValueError, match="preserve the source memory kind"):
        store.merge(
            (first.memory.memory_id, second.memory.memory_id),
            wrong_kind,
            now=now,
        )

    assert store.count(include_superseded=False) == 2


def test_merge_requires_retaining_provenance_ids(tmp_path):
    store = MemoryStore(tmp_path / "memory-provenance.sqlite3")
    first = store.save(
        MemoryRecord(
            kind="semantic",
            content="Fact from an event.",
            source_event_ids=["event-001"],
        )
    )
    second = store.save(
        MemoryRecord(
            kind="semantic",
            content="Another fact from an event.",
            source_event_ids=["event-002"],
        )
    )

    with pytest.raises(ValueError, match="retain all source event provenance"):
        store.merge(
            (first.memory.memory_id, second.memory.memory_id),
            MemoryRecord(
                kind="semantic",
                content="Merged facts.",
                source_event_ids=["event-001"],
            ),
        )

    assert store.count(include_superseded=False) == 2
