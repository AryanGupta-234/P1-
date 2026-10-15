from datetime import datetime, timedelta, timezone

import pytest

from aie.memory import MemoryStore


def test_memory_round_trip_and_default_sensitive_filtering(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    ordinary = store.add(
        "User prefers concise technical explanations",
        kind="semantic",
        provenance_ids=["chat:123", "event:456"],
        confidence=0.8,
        verification="supported",
        tags=["preference", "style"],
    )
    secret = store.add(
        "Private record",
        sensitivity="sensitive",
    )
    assert store.get(ordinary["memory_id"])["provenance_ids"] == ["chat:123", "event:456"]
    assert [item["memory_id"] for item in store.search("technical")] == [ordinary["memory_id"]]
    assert secret["memory_id"] not in {item["memory_id"] for item in store.search("")}
    assert secret["memory_id"] in {item["memory_id"] for item in store.search("", include_sensitive=True)}


def test_memory_ttl_and_explicit_delete(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    expiring = store.add("temporary note", ttl_days=1)
    permanent = store.add("durable note")
    future = datetime.now(timezone.utc) + timedelta(days=2)
    assert store.prune_expired(now=future) == 1
    assert store.get(expiring["memory_id"]) is None
    assert store.get(permanent["memory_id"]) is not None
    assert store.delete(permanent["memory_id"]) is True
    assert store.delete(permanent["memory_id"]) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "unknown"},
        {"content": ""},
        {"confidence": float("nan")},
        {"sensitivity": "unknown"},
        {"verification": "unknown"},
        {"ttl_days": 0},
        {"provenance_ids": [""]},
        {"tags": [""]},
    ],
)
def test_memory_rejects_invalid_metadata(tmp_path, kwargs):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    content = kwargs.pop("content", "valid note")
    with pytest.raises(ValueError):
        store.add(content, **kwargs)


def test_memory_search_is_bounded_and_kind_filterable(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.add("Plan launch", kind="prospective")
    store.add("Launch happened", kind="episodic")
    assert len(store.search("launch", kind="episodic", limit=1)) == 1
    with pytest.raises(ValueError):
        store.search("x", limit=101)
