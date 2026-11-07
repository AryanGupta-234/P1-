import pytest

from apex.store import UnifiedDataStore


def test_profile_has_safe_default_and_accepts_explicit_updates(tmp_path):
    store = UnifiedDataStore(tmp_path / "apex.sqlite3")

    assert store.get_profile() == {"preferred_salutation": "sir"}

    updated = store.update_user_profile({
        "display_name": "Aryan",
        "preferred_salutation": "sir",
        "interaction_style": "concise and technical",
    })

    assert updated["display_name"] == "Aryan"
    assert updated["preferred_salutation"] == "sir"
    assert updated["interaction_style"] == "concise and technical"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"windows_username": "someone"},
        {"display_name": ""},
        {"display_name": "x" * 81},
        {"locale": 123},
        {"display_name": "A", "preferred_salutation": "sir", "locale": "en", "interaction_style": "x", "other": "no"},
    ],
)
def test_profile_rejects_unknown_or_unbounded_fields(tmp_path, fields):
    store = UnifiedDataStore(tmp_path / "apex.sqlite3")
    with pytest.raises(ValueError):
        store.update_user_profile(fields)


def test_profile_updates_survive_store_reopen(tmp_path):
    path = tmp_path / "apex.sqlite3"
    store = UnifiedDataStore(path)
    store.update_user_profile({"preferred_salutation": "sir", "locale": "en-IN"})

    reopened = UnifiedDataStore(path)
    assert reopened.get_profile()["preferred_salutation"] == "sir"
    assert reopened.get_profile()["locale"] == "en-IN"
