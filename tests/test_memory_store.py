from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from aie.contracts import AIEEvent, EntityRef
from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore
from aie.store import EventStore


def test_memory_save_reload_and_keyword_retrieval(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    record = store.save(MemoryRecord(
        kind="semantic",
        content="P1 uses local Ollama for private reasoning tasks.",
        tags=["model-routing", "local inference"],
    ))
    loaded = store.get(record.memory_id)
    assert loaded is not None
    assert loaded.memory.content == record.content
    hits = store.search("ollama local reasoning")
    assert hits
    assert hits[0].memory.memory_id == record.memory_id
    assert hits[0].score > 0


def test_sensitive_memories_are_excluded_from_retrieval_by_default(tmp_path):
    store = MemoryStore(tmp_path / "sensitive.sqlite3")
    secret = store.save(MemoryRecord(
        kind="episodic",
        content="Sensitive private account recovery detail.",
        sensitivity="sensitive",
        tags=["private"],
    ))
    assert store.search("account recovery") == []
    hits = store.search("account recovery", include_sensitive=True)
    assert hits[0].memory.memory_id == secret.memory_id


def test_expired_memories_are_hidden_and_can_be_pruned(tmp_path):
    store = MemoryStore(tmp_path / "expiry.sqlite3")
    now = datetime.now(timezone.utc)
    expiring = store.save(MemoryRecord(
        kind="working",
        content="Temporary task context.",
        created_at=now - timedelta(hours=1),
        expires_at=now + timedelta(minutes=5),
    ))
    assert store.list_memories(now=now)
    assert store.list_memories(now=now + timedelta(minutes=6)) == []
    assert store.prune_expired(now=now + timedelta(minutes=6)) == 1
    assert store.get(expiring.memory_id) is None


def test_correction_supersedes_previous_version_without_erasing_history(tmp_path):
    store = MemoryStore(tmp_path / "correction.sqlite3")
    first = store.save(MemoryRecord(
        kind="semantic",
        content="The local default model is qwen2.5:7b.",
        tags=["model"],
    ))
    second = store.save(MemoryRecord(
        kind="semantic",
        content="The local default model is qwen2.5:3b.",
        tags=["model"],
        supersedes_id=first.memory_id,
    ))
    assert store.get(first.memory_id) is None
    prior = store.get(first.memory_id, include_superseded=True)
    assert prior is not None
    assert prior.status == "superseded"
    assert store.get(second.memory_id) is not None
    assert store.count() == 2


def test_correction_requires_existing_active_memory_of_same_kind(tmp_path):
    store = MemoryStore(tmp_path / "invalid-correction.sqlite3")
    with pytest.raises(ValueError, match="not found"):
        store.save(MemoryRecord(
            kind="semantic",
            content="New memory.",
            supersedes_id="missing",
        ))


def test_memory_provenance_requires_existing_event_ids(tmp_path):
    store = MemoryStore(tmp_path / "provenance.sqlite3")
    events = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError, match="event_store is required"):
        store.save(MemoryRecord(
            kind="episodic",
            content="Remembered from a source event.",
            source_event_ids=["event-1"],
        ))
    with pytest.raises(ValueError, match="not found"):
        store.save(
            MemoryRecord(
                kind="episodic",
                content="Remembered from a source event.",
                source_event_ids=["missing"],
            ),
            event_store=events,
        )

    source = AIEEvent(
        event_id="event-1",
        host_id="host",
        source="test",
        event_type="host.snapshot",
        entity=EntityRef(type="host", name="test"),
    )
    events.append(source)
    saved = store.save(
        MemoryRecord(
            kind="episodic",
            content="This observation was explicitly reviewed.",
            source_event_ids=["event-1"],
        ),
        event_store=events,
    )
    assert saved.source_event_ids == ["event-1"]


def test_memory_delete_is_explicit_and_permanent(tmp_path):
    store = MemoryStore(tmp_path / "delete.sqlite3")
    item = store.save(MemoryRecord(kind="procedural", content="Review test results before merging."))
    assert store.delete(item.memory_id) is True
    assert store.delete(item.memory_id) is False
    assert store.count() == 0


def test_memory_rejects_naive_timestamps_and_invalid_tags():
    with pytest.raises(ValidationError):
        MemoryRecord(
            kind="episodic",
            content="bad timestamp",
            created_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        MemoryRecord(kind="episodic", content="bad tag", tags=["invalid tag ?"])


def test_memory_search_is_kind_filterable_and_bounded(tmp_path):
    store = MemoryStore(tmp_path / "kinds.sqlite3")
    store.save(MemoryRecord(kind="semantic", content="Windows event logs contain metadata records."))
    store.save(MemoryRecord(kind="episodic", content="Windows browser stalled this morning."))

    hits = store.search("Windows browser", kind="episodic")
    assert len(hits) == 1
    assert hits[0].memory.kind == "episodic"
    with pytest.raises(ValueError):
        store.search("Windows", limit=0)



def test_memory_save_keeps_timestamp_order_when_source_clock_is_ahead(tmp_path):
    store = MemoryStore(tmp_path / "clock-skew.sqlite3")
    future_created_at = datetime.now(timezone.utc) + timedelta(days=1)
    record = MemoryRecord(
        kind="working",
        content="Clock-skew regression fixture.",
        created_at=future_created_at,
        updated_at=future_created_at,
    )

    saved = store.save(record)
    loaded = store.get(saved.memory_id)

    assert saved.updated_at >= saved.created_at
    assert loaded is not None
    assert loaded.memory.updated_at >= loaded.memory.created_at
