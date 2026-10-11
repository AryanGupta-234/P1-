from datetime import datetime, timedelta, timezone

from aie.context.evidence import assess_evidence, find_explicit_contradictions
from aie.contracts import AIEEvent, EntityRef


def make_event(event_id, seconds_ago, state):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc) - timedelta(seconds=seconds_ago),
        host_id="host-a",
        source="browser.extension",
        event_type="browser.video.snapshot",
        entity=EntityRef(type="video", name="active-video", stable_id="video-1"),
        data={"playback_state": state},
        confidence=0.8,
    )


def test_assess_evidence_weights_freshness_without_calling_it_probability():
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    assessments = assess_evidence(
        [make_event("fresh", 0, "playing"), make_event("old", 120, "playing")],
        now=now,
        max_age_seconds=90,
        half_life_seconds=60,
    )

    assert assessments[0].fresh is True
    assert assessments[0].time_weight == 1.0
    assert assessments[0].effective_confidence == 0.8
    assert assessments[1].fresh is False
    assert assessments[1].time_weight == 0.0
    assert assessments[1].effective_confidence == 0.0


def test_contradiction_detection_requires_same_fact_and_near_simultaneous_states():
    base = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    first = make_event("first", 0, "playing").model_copy(update={"timestamp": base})
    second = make_event("second", 0.5, "stalled").model_copy(
        update={"timestamp": base - timedelta(seconds=0.5)}
    )
    late = make_event("late", 4, "stalled").model_copy(
        update={"timestamp": base - timedelta(seconds=4)}
    )

    contradictions = find_explicit_contradictions([first, second, late])

    assert len(contradictions) == 1
    assert set(contradictions[0].event_ids) == {"first", "second"}
    assert set(contradictions[0].values) == {"playing", "stalled"}


def test_non_state_payloads_and_different_fact_keys_do_not_conflict():
    first = make_event("one", 0, "playing")
    second = make_event("two", 0.2, "playing").model_copy(
        update={"entity": EntityRef(type="video", name="other-video", stable_id="video-2")}
    )

    assert find_explicit_contradictions([first, second]) == ()
