from senti.store import UnifiedDataStore


def test_memory_store_search_hides_sensitive_entries_and_supports_forget(tmp_path):
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    visible_id = store.add_memory(
        namespace="project",
        memory_type="project_context",
        payload={"project": "SENTI", "note": "memory retrieval architecture"},
        source="explicit_user_request",
    )
    private_id = store.add_memory(
        namespace="project",
        memory_type="fact",
        payload={"note": "private note"},
        source="explicit_user_request",
        sensitivity="sensitive",
    )

    results = store.search_memories("retrieval architecture", namespace="project")
    assert [row["memory_id"] for row in results] == [visible_id]
    assert store.forget_memory(visible_id) is True
    assert store.forget_memory(visible_id) is False
    assert store.search_memories("retrieval", namespace="project") == []
    assert store.forget_memory(private_id) is True


def test_memory_store_rejects_credential_like_fields_and_bounds_payload(tmp_path):
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    try:
        store.add_memory(
            namespace="personal",
            memory_type="fact",
            payload={"api_token": "must not be stored"},
            source="explicit_user_request",
        )
    except ValueError as exc:
        assert "credential-like" in str(exc)
    else:
        raise AssertionError("credential-like memory field was accepted")


def test_memory_store_expiration_and_runtime_flags(tmp_path):
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    store.add_memory(
        namespace="personal",
        memory_type="fact",
        payload={"note": "expired"},
        source="test",
        expires_at="2000-01-01T00:00:00+00:00",
    )
    assert store.prune_expired_memories() == 1
    assert store.get_runtime_flag("emergency_stop", False) is False
    store.set_runtime_flag("emergency_stop", True)
    assert store.get_runtime_flag("emergency_stop", False) is True
    assert store.integrity_check()
