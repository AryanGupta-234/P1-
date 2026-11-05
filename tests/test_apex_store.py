from apex.store import UnifiedDataStore

def test_unified_store_persists_profile_messages_and_change_sequence(tmp_path):
    store = UnifiedDataStore(tmp_path / "apex.sqlite3")
    store.save_profile({"preferred_salutation": "sir", "display_name": "Aryan"})
    assert store.get_profile()["preferred_salutation"] == "sir"
    conversation = store.ensure_conversation()
    store.append_message(conversation, "user", "hello")
    store.append_message(conversation, "assistant", "hello sir")
    assert [m["role"] for m in store.recent_messages(conversation)] == ["user", "assistant"]
    assert store.integrity_check()
    changes = store.recent_changes()
    assert len(changes) >= 4
    assert changes[-1]["domain"] == "message"
