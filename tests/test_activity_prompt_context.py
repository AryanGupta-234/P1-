from datetime import datetime, timedelta, timezone

import pytest

from aie.context.activity_context import build_activity_prompt_context
from aie.contracts import AIEEvent, EntityRef
from aie.store import EventStore


def event(event_id, event_type, data, *, seconds_ago=1, sensitivity="internal"):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
        host_id="host-a",
        source="test",
        event_type=event_type,
        entity=EntityRef(type="test", name="test"),
        sensitivity=sensitivity,
        data=data,
    )


def test_activity_context_uses_only_safe_projection_and_event_provenance(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.append_many([
        event(
            "foreground-1",
            "window.foreground_changed",
            {
                "pid": 100,
                "process_name": "msedge.exe",
                "window_class": "Chrome_WidgetWin_1",
                "window_title": "PRIVATE WINDOW TITLE",
            },
        ),
        event(
            "video-1",
            "browser.video.snapshot",
            {
                "playback_state": "stalled",
                "stall_count": 2,
                "buffered_ahead_seconds": 0.2,
            },
        ),
        event(
            "eventlog-1",
            "windows.eventlog.record",
            {
                "channel": "System",
                "event_id": 1001,
                "message": "PRIVATE EVENT LOG MESSAGE",
            },
        ),
        event(
            "diagnostic-1",
            "diagnostic.video_finding",
            {
                "cause": "stream_buffer_starvation",
                "severity": "medium",
                "recommendation": "PRIVATE INTERNAL RECOMMENDATION",
            },
        ),
        event(
            "sensitive-1",
            "window.foreground_changed",
            {
                "pid": 200,
                "process_name": "credential-manager.exe",
                "window_title": "PRIVATE SENSITIVE TITLE",
            },
            sensitivity="sensitive",
        ),
    ])

    result = build_activity_prompt_context(store)

    assert result.session_count == 1
    assert result.signal_count == 4
    assert set(result.event_ids) == {
        "foreground-1",
        "video-1",
        "eventlog-1",
        "diagnostic-1",
    }
    assert "msedge.exe" in result.content
    assert "stalled" in result.content
    assert "System Event Log metadata" in result.content
    assert "PRIVATE" not in result.content
    assert "credential-manager.exe" not in result.content
    assert "recommendation" not in result.content


def test_activity_context_is_empty_when_no_recent_safe_observations(tmp_path):
    store = EventStore(tmp_path / "empty.sqlite3")
    store.append(event(
        "sensitive-1",
        "window.foreground_changed",
        {"process_name": "app.exe", "window_title": "secret"},
        sensitivity="sensitive",
    ))

    result = build_activity_prompt_context(store)

    assert result.content == ""
    assert result.event_ids == ()
    assert result.signal_count == 0


def test_activity_context_enforces_lookback_and_size_budgets(tmp_path):
    store = EventStore(tmp_path / "bounded.sqlite3")
    store.append(event(
        "old-1",
        "window.foreground_changed",
        {"process_name": "old.exe"},
        seconds_ago=7200,
    ))
    result = build_activity_prompt_context(
        store,
        lookback_minutes=30,
        max_characters=800,
    )

    assert result.content == ""
    assert result.event_ids == ()

    with pytest.raises(ValueError):
        build_activity_prompt_context(store, lookback_minutes=0)
    with pytest.raises(ValueError):
        build_activity_prompt_context(store, max_characters=100)
