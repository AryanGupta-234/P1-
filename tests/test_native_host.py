import io
import struct
import uuid

import pytest

from aie.browser.native_host import (
    MAX_MESSAGE_BYTES,
    event_from_browser_payload,
    iter_native_messages,
    run_host,
    write_native_message,
)
from aie.store import EventStore


def make_payload(**overrides):
    message = {
        "kind": "video_snapshot",
        "media_session_id": str(uuid.uuid4()),
        "playback_state": "waiting",
        "stall_count": 2,
        "observation_window_seconds": 60,
        "buffered_ahead_seconds": 0.7,
        "playback_progress_delta_seconds": 0.0,
        "dropped_frames_pct": 2.5,
    }
    message.update(overrides)
    return message


def test_browser_payload_becomes_minimized_normalized_event():
    event = event_from_browser_payload(make_payload())

    assert event.source == "browser.extension"
    assert event.event_type == "browser.video.snapshot"
    assert event.data["playback_state"] == "waiting"
    assert event.data["stall_count"] == 2
    assert event.data["buffered_ahead_seconds"] == 0.7
    assert "url" not in event.data
    assert "page_text" not in event.data


@pytest.mark.parametrize(
    "changes",
    [
        {"playback_state": "unknown"},
        {"stall_count": -1},
        {"stall_count": True},
        {"observation_window_seconds": 0},
        {"dropped_frames_pct": 101},
        {"url": "https://private.example/path"},
    ],
)
def test_rejects_invalid_or_unapproved_browser_fields(changes):
    with pytest.raises(ValueError):
        event_from_browser_payload(make_payload(**changes))


def test_native_messaging_frame_round_trip():
    message = make_payload()
    encoded = io.BytesIO()
    write_native_message(encoded, message)
    encoded.seek(0)

    assert list(iter_native_messages(encoded)) == [message]


def test_native_host_persists_browser_event(tmp_path):
    incoming = io.BytesIO()
    write_native_message(incoming, make_payload())
    incoming.seek(0)
    outgoing = io.BytesIO()
    store = EventStore(tmp_path / "events.sqlite3")

    assert run_host(incoming, outgoing, store) == 1
    assert store.count() == 2
    stored = store.recent(2)
    assert {item.event_type for item in stored} == {
        "browser.video.snapshot", "diagnostic.video_finding"
    }
    finding = next(item for item in stored if item.event_type == "diagnostic.video_finding")
    assert finding.data["cause"] == "stream_buffer_starvation"
    assert finding.data["action_executed"] is False
    response = list(iter_native_messages(io.BytesIO(outgoing.getvalue())))
    assert response[0]["ok"] is True


def test_native_host_rejects_oversized_frame():
    stream = io.BytesIO(struct.pack("<I", MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ValueError):
        list(iter_native_messages(stream))
