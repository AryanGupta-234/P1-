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


def test_reviewed_knowledge_import_is_idempotent_and_provenance_preserving(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    first = store.import_reviewed_knowledge(
        "knowledge-1", "Repeatedly verified display navigation",
        provenance_ids=["experience-1", "event-1"], tags=["task:display"],
    )
    second = store.import_reviewed_knowledge(
        "knowledge-1", "Repeatedly verified display navigation",
        provenance_ids=["experience-1", "event-1"], tags=["task:display"],
    )
    assert first["memory_id"] == second["memory_id"]
    assert first["kind"] == "semantic"
    assert first["verification"] == "supported"
    assert first["provenance_ids"] == ["experience-1", "event-1"]
    assert len(store.search("display", kind="semantic")) == 1


def test_reviewed_knowledge_import_requires_provenance(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    with pytest.raises(ValueError, match="provenance"):
        store.import_reviewed_knowledge("knowledge-2", "No provenance", provenance_ids=[])


def test_memory_search_recency_is_bounded_and_configurable(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    old = store.add("shared topic old", confidence=1.0)
    recent = store.add("shared topic recent", confidence=0.1)
    with store._connect() as db:
        db.execute("UPDATE memories SET created_at=? WHERE memory_id=?",
                   ((datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),
                    old["memory_id"]))
    results = store.search("shared topic", recency_weight=1.0, recency_half_life_days=30)
    assert results[0]["memory_id"] == recent["memory_id"]
    stable = store.search("shared topic", recency_weight=0.0)
    assert {item["memory_id"] for item in stable} == {old["memory_id"], recent["memory_id"]}


def test_embedding_index_and_semantic_search(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    first = store.add("Configure the display resolution", kind="semantic")
    second = store.add("Prepare a vegetable soup recipe", kind="semantic")
    secret = store.add("Private display notes", sensitivity="sensitive")
    assert len(store.get_embedding_candidates("local-embed")) == 2
    store.store_embedding(first["memory_id"], "local-embed", [1.0, 0.0], expected_content=first["content"])
    store.store_embedding(second["memory_id"], "local-embed", [0.0, 1.0], expected_content=second["content"])
    store.store_embedding(secret["memory_id"], "local-embed", [0.9, 0.1], expected_content=secret["content"])
    results = store.semantic_search([0.95, 0.05], "local-embed")
    assert results[0]["memory_id"] == first["memory_id"]
    assert secret["memory_id"] not in {item["memory_id"] for item in results}
    assert results[0]["similarity"] > 0.99


def test_embedding_stale_content_is_excluded_and_reindexed(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    record = store.add("Original content")
    store.store_embedding(record["memory_id"], "embed", [1.0, 0.0],
                          expected_content=record["content"])
    assert store.get_embedding_candidates("embed") == []
    assert store.revise(record["memory_id"], content="Changed content")
    assert [item["memory_id"] for item in store.get_embedding_candidates("embed")] == [record["memory_id"]]
    assert store.semantic_search([1.0, 0.0], "embed") == []


def test_embedding_validation_and_dimension_mismatch(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    record = store.add("Dimension test")
    with pytest.raises(ValueError, match="finite"):
        store.store_embedding(record["memory_id"], "embed", [float("nan")],
                              expected_content=record["content"])
    store.store_embedding(record["memory_id"], "embed", [1.0, 0.0],
                          expected_content=record["content"])
    assert store.semantic_search([1.0], "embed") == []
    with pytest.raises(ValueError, match="non-zero"):
        store.semantic_search([0.0, 0.0], "embed")


def test_semantic_near_duplicates_are_candidates_only(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    first = store.add("Display settings instructions")
    second = store.add("How to configure screen display")
    store.store_embedding(first["memory_id"], "embed", [1.0, 0.0],
                          expected_content=first["content"])
    store.store_embedding(second["memory_id"], "embed", [0.99, 0.01],
                          expected_content=second["content"])
    candidates = store.find_near_duplicates(first["memory_id"], "embed", threshold=0.9)
    assert len(candidates) == 1
    assert candidates[0]["memory_id"] == second["memory_id"]
    assert candidates[0]["candidate_only"] is True
    assert candidates[0]["automatic_merge"] is False


def test_memory_delete_and_expiry_remove_embedding_indexes(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    doomed = store.add("Temporary indexed memory", ttl_days=1)
    store.store_embedding(doomed["memory_id"], "embed", [1.0, 0.0],
                          expected_content=doomed["content"])
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 1
    future = datetime.now(timezone.utc) + timedelta(days=2)
    assert store.prune_expired(now=future) == 1
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0
    retained = store.add("Delete indexed memory")
    store.store_embedding(retained["memory_id"], "embed", [1.0, 0.0],
                          expected_content=retained["content"])
    assert store.delete(retained["memory_id"]) is True
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0
