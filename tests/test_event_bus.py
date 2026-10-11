from datetime import datetime, timezone

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.event_bus import EventBus


def event(event_id: str) -> AIEEvent:
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
        host_id="host-a",
        source="test",
        event_type="test.event",
        entity=EntityRef(type="test", name=event_id),
    )


def test_publish_preserves_order_and_calls_sinks_in_registration_order():
    bus = EventBus(max_batch_size=4)
    calls = []

    def first(events):
        calls.append(("first", [item.event_id for item in events]))
        return len(events)

    def second(events):
        calls.append(("second", [item.event_id for item in events]))
        return len(events)

    bus.subscribe("first", first)
    bus.subscribe("second", second)

    handled = bus.publish([event("a"), event("b")])

    assert handled == {"first": 2, "second": 2}
    assert bus.sink_names == ("first", "second")
    assert calls == [
        ("first", ["a", "b"]),
        ("second", ["a", "b"]),
    ]


def test_bus_rejects_duplicate_sinks_and_oversized_batches():
    bus = EventBus(max_batch_size=1)
    bus.subscribe("sink", lambda events: len(tuple(events)))

    with pytest.raises(ValueError, match="duplicate"):
        bus.subscribe("sink", lambda events: 0)

    with pytest.raises(ValueError, match="exceeds"):
        bus.publish([event("a"), event("b")])


def test_sink_failure_is_not_silently_dropped():
    bus = EventBus()
    bus.subscribe("failing", lambda events: (_ for _ in ()).throw(RuntimeError("sink down")))

    with pytest.raises(RuntimeError, match="sink down"):
        bus.publish([event("a")])


def test_sink_return_contract_is_validated():
    bus = EventBus()
    bus.subscribe("bad", lambda events: -1)

    with pytest.raises(TypeError, match="non-negative"):
        bus.publish([event("a")])
