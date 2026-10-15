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



def test_memory_correction_preserves_identity_and_provenance(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    original = store.add(
        "old wording", provenance_ids=["source-1"], confidence=0.4
    )
    assert store.revise(
        original["memory_id"], content="corrected wording",
        confidence=0.9, verification="verified",
    )
    revised = store.get(original["memory_id"])
    assert revised["content"] == "corrected wording"
    assert revised["confidence"] == 0.9
    assert revised["verification"] == "verified"
    assert revised["provenance_ids"] == ["source-1"]


def test_memory_export_is_new_file_and_sensitive_is_opt_in(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.add("ordinary note")
    store.add("sensitive note", sensitivity="sensitive")
    output = tmp_path / "exports" / "memory.jsonl"
    assert store.export_jsonl(output) == 1
    assert "ordinary note" in output.read_text(encoding="utf-8")
    assert "sensitive note" not in output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        store.export_jsonl(output)
    full = tmp_path / "exports" / "all-memory.jsonl"
    assert store.export_jsonl(full, include_sensitive=True) == 2



def test_memory_correction_history_is_preserved_and_deleted_with_record(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    original = store.add("first version")
    store.revise(original["memory_id"], content="second version")
    store.revise(original["memory_id"], content="third version")
    history = store.history(original["memory_id"])
    assert len(history) == 2
    assert history[0]["previous"]["content"] == "second version"
    assert history[1]["previous"]["content"] == "first version"
    assert store.delete(original["memory_id"])
    assert store.history(original["memory_id"]) == []
