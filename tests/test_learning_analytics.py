from datetime import datetime, timezone

from aie.contracts import AIEEvent, EntityRef
from aie.learning.analytics import load_feedback_summary, summarize_feedback
from aie.store import EventStore


def feedback_event(cause, outcome, event_id):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        host_id="host-a",
        source="user.feedback",
        event_type="diagnostic.user_feedback",
        entity=EntityRef(type="diagnostic_feedback", name=cause),
        data={"cause": cause, "outcome": outcome},
        evidence_kind="observed",
    )


def test_feedback_summary_counts_only_attempted_outcomes():
    summaries = summarize_feedback([
        feedback_event("stream_buffer_starvation", "resolved", "1"),
        feedback_event("stream_buffer_starvation", "resolved", "2"),
        feedback_event("stream_buffer_starvation", "not_resolved", "3"),
        feedback_event("stream_buffer_starvation", "not_attempted", "4"),
        feedback_event("other_cause", "not_attempted", "5"),
    ])

    result = next(item for item in summaries if item.cause == "stream_buffer_starvation")
    assert result.resolved == 2
    assert result.not_resolved == 1
    assert result.not_attempted == 1
    assert result.attempted == 3
    assert result.resolution_rate == 2 / 3

    no_attempts = next(item for item in summaries if item.cause == "other_cause")
    assert no_attempts.resolution_rate is None


def test_feedback_summary_ignores_non_feedback_and_malformed_events():
    malformed = AIEEvent(
        event_id="bad",
        host_id="host-a",
        source="user.feedback",
        event_type="diagnostic.user_feedback",
        entity=EntityRef(type="diagnostic_feedback", name="x"),
        data={"cause": "x", "outcome": "maybe"},
    )
    unrelated = AIEEvent(
        event_id="not-feedback",
        host_id="host-a",
        source="unit",
        event_type="windows.eventlog.record",
        entity=EntityRef(type="windows_event", name="test"),
    )
    assert summarize_feedback([malformed, unrelated]) == []


def test_load_feedback_summary_reads_event_store(tmp_path):
    store = EventStore(tmp_path / "feedback-report.sqlite3")
    store.append(feedback_event("high_network_latency", "resolved", "one"))
    store.append(feedback_event("high_network_latency", "not_resolved", "two"))

    result = load_feedback_summary(store)

    assert len(result) == 1
    assert result[0].cause == "high_network_latency"
    assert result[0].attempted == 2
    assert result[0].resolution_rate == 0.5
