from aie.contracts import AIEEvent, EntityRef
from aie.store import EventStore


def event():
    return AIEEvent(event_id="stable-id", host_id="test", source="unit",
                    event_type="sample", entity=EntityRef(type="test", name="sample"))


def test_durable_store_and_deduplication(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    assert store.append(event()) is True
    assert store.append(event()) is False
    reopened = EventStore(path)
    assert reopened.count() == 1
    assert reopened.recent(1)[0].event_id == "stable-id"
