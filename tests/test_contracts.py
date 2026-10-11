from aie.contracts import AIEEvent, EntityRef


def test_event_has_version_and_timezone():
    event = AIEEvent(host_id="test", source="unit", event_type="sample",
                     entity=EntityRef(type="test", name="sample"))
    assert event.schema_version == "1.0"
    assert event.timestamp.tzinfo is not None
    assert event.evidence_kind == "observed"


def test_confidence_is_bounded():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AIEEvent(host_id="test", source="unit", event_type="sample",
                 entity=EntityRef(type="test", name="sample"), confidence=1.5)
