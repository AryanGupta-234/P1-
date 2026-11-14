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


def test_memory_correction_keeps_provenance_and_bumps_version(tmp_path):
    import pytest
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    memory_id = store.add_memory(namespace="preferences", memory_type="preference",
                                 payload={"theme": "light"}, source="explicit_user_request")
    updated = store.update_memory(memory_id, payload={"theme": "dark"}, reason="sir prefers dark mode now")
    assert updated["payload"]["theme"] == "dark"
    assert updated["payload"]["_previous"]["payload"] == {"theme": "light"}
    assert updated["version"] == 2 and updated["source"] == "user_correction"
    with pytest.raises(ValueError):
        store.update_memory(memory_id, payload={"theme": "x"}, reason="")
    with pytest.raises(ValueError):
        store.update_memory("missing", payload={"theme": "x"}, reason="r")


def test_update_memory_tool_is_simulated_with_current_value(tmp_path):
    from senti.tools.phase1_tools import register_phase1_tools
    from senti.tools.registry import CapabilityRegistry
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    memory_id = store.add_memory(namespace="personal", memory_type="fact",
                                 payload={"city": "Delhi"}, source="explicit_user_request")
    registry = CapabilityRegistry()
    register_phase1_tools(registry, store)
    preview = registry.simulate("senti_update_memory", {"memory_id": memory_id, "payload": {"city": "Lucknow"},
                                                        "reason": "moved"})
    assert preview["current_state"] == {"city": "Delhi"} and preview["intended_state"] == {"city": "Lucknow"}
    result = registry.dispatch("senti_update_memory", {"memory_id": memory_id, "payload": {"city": "Lucknow"},
                                                       "reason": "moved"}, approval=lambda *a: True)
    assert result.status == "succeeded" and store.get_memory(memory_id)["payload"]["city"] == "Lucknow"
