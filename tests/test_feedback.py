from datetime import datetime, timezone

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.learning.feedback import FeedbackRequest, record_diagnostic_feedback
from aie.store import EventStore


def diagnostic_event():
    return AIEEvent(
        event_id="diag-001",
        timestamp=datetime.now(timezone.utc),
        host_id="host-a",
        source="aie.diagnostics.video",
        event_type="diagnostic.video_finding",
        entity=EntityRef(type="diagnostic", name="stream_buffer_starvation"),
        data={"cause": "stream_buffer_starvation", "action_executed": False},
        evidence_kind="derived",
    )


def test_feedback_is_linked_to_finding_and_saved_locally(tmp_path):
    store = EventStore(tmp_path / "feedback.sqlite3")
    target = diagnostic_event()
    store.append(target)

    feedback = record_diagnostic_feedback(
        store,
        FeedbackRequest(
            diagnostic_event_id=target.event_id,
            outcome="resolved",
            note="Playback became stable after lowering quality.",
        ),
    )

    assert feedback.event_type == "diagnostic.user_feedback"
    assert feedback.correlation_id == target.event_id
    assert feedback.data["target_event_id"] == target.event_id
    assert feedback.data["outcome"] == "resolved"
    assert feedback.data["action_executed_by_assistant"] is False
    assert feedback.sensitivity == "sensitive"
    assert store.get(feedback.event_id) is not None
    assert store.get(target.event_id).event_type == "diagnostic.video_finding"


def test_feedback_without_note_is_internal(tmp_path):
    store = EventStore(tmp_path / "feedback.sqlite3")
    store.append(diagnostic_event())

    feedback = record_diagnostic_feedback(
        store,
        FeedbackRequest(diagnostic_event_id="diag-001", outcome="not_attempted"),
    )

    assert feedback.sensitivity == "internal"
    assert "user_note" not in feedback.data


def test_feedback_rejects_missing_or_non_diagnostic_event(tmp_path):
    store = EventStore(tmp_path / "feedback.sqlite3")

    with pytest.raises(ValueError, match="was not found"):
        record_diagnostic_feedback(
            store,
            FeedbackRequest(diagnostic_event_id="missing", outcome="resolved"),
        )

    wrong_type = AIEEvent(
        event_id="system-001",
        host_id="host-a",
        source="unit",
        event_type="host.snapshot",
        entity=EntityRef(type="host", name="pc"),
    )
    store.append(wrong_type)
    with pytest.raises(ValueError, match="only reference"):
        record_diagnostic_feedback(
            store,
            FeedbackRequest(diagnostic_event_id="system-001", outcome="resolved"),
        )
