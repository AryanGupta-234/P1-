from datetime import datetime, timezone

from aie.contracts import AIEEvent, EntityRef
from aie.desktop.notifications import (
    DiagnosticNotificationPoller,
    NotificationPreferences,
    NotificationPreferencesStore,
)
from aie.store import EventStore


def make_event(event_type="diagnostic.video_finding"):
    return AIEEvent(
        host_id="test-host",
        source="test",
        event_type=event_type,
        entity=EntityRef(type="diagnostic", name="local"),
        data={
            "cause": "private diagnostic detail",
            "window_title": "must never appear in notification",
            "recommendation": "private recommendation",
        },
    )


def test_preferences_default_off_and_persist_quiet_hours(tmp_path):
    store = NotificationPreferencesStore(tmp_path / "notifications.json")
    defaults = store.load()
    assert defaults.enabled is False
    assert defaults.quiet_start == "22:00"
    assert defaults.quiet_end == "07:00"

    saved = NotificationPreferences(
        enabled=True,
        quiet_start="21:30",
        quiet_end="06:45",
    )
    store.save(saved)
    assert store.load() == saved


def test_quiet_hours_support_overnight_windows_and_disabled_equal_times():
    prefs = NotificationPreferences(
        enabled=True,
        quiet_start="22:00",
        quiet_end="07:00",
    )
    assert prefs.is_quiet(datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc))
    assert prefs.is_quiet(datetime(2026, 10, 11, 6, 59, tzinfo=timezone.utc))
    assert not prefs.is_quiet(datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc))

    no_quiet = NotificationPreferences(enabled=True, quiet_start="00:00", quiet_end="00:00")
    assert not no_quiet.is_quiet(datetime(2026, 10, 11, 23, 59, tzinfo=timezone.utc))


def test_notification_polling_is_opt_in_and_uses_generic_text(tmp_path):
    events = EventStore(tmp_path / "events.sqlite3")
    preferences = NotificationPreferencesStore(tmp_path / "notifications.json")
    paused = {"value": False}
    poller = DiagnosticNotificationPoller(
        event_store=events,
        preferences=preferences,
        is_paused=lambda: paused["value"],
    )

    events.append(make_event())
    assert poller.poll(now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)) == []

    preferences.save(
        NotificationPreferences(
            enabled=True,
            quiet_start="00:00",
            quiet_end="00:00",
        )
    )
    events.append(make_event())
    result = poller.poll(now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc))
    assert len(result) == 1
    assert result[0].title == "P1- diagnostic finding"
    assert "window_title" not in result[0].message
    assert "private" not in result[0].message

    events.append(make_event())
    paused["value"] = True
    assert poller.poll(now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)) == []
    paused["value"] = False
    assert poller.poll(now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)) == []


def test_quiet_hours_suppress_new_notifications_without_backlog(tmp_path):
    events = EventStore(tmp_path / "quiet-events.sqlite3")
    preferences = NotificationPreferencesStore(tmp_path / "quiet.json")
    preferences.save(
        NotificationPreferences(
            enabled=True,
            quiet_start="11:00",
            quiet_end="13:00",
        )
    )
    poller = DiagnosticNotificationPoller(
        event_store=events,
        preferences=preferences,
        is_paused=lambda: False,
    )
    events.append(make_event())
    quiet_now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    assert poller.poll(now=quiet_now) == []

    preferences.save(
        NotificationPreferences(
            enabled=True,
            quiet_start="00:00",
            quiet_end="00:00",
        )
    )
    assert poller.poll(now=quiet_now) == []
