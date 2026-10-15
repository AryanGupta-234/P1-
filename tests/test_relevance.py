from datetime import datetime, timedelta, timezone

import pytest

from aie.relevance import rank_environment_state
from aie.state_model import project_environment_state
from aie.contracts import AIEEvent, EntityRef


def event(event_id, kind, when, *, data=None, name="demo.exe", entity_type="process", stable=None):
    return AIEEvent(
        event_id=event_id, timestamp=when, host_id="host-a", source="test",
        event_type=kind,
        entity=EntityRef(type=entity_type, name=name, stable_id=stable),
        data=data or {},
    )


def test_ranking_is_deterministic_and_explains_active_etw_confirmed_process():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        event("start", "process.started_observed", now - timedelta(hours=1),
              data={"pid": 7, "create_time": (now - timedelta(hours=1)).timestamp()}),
        event("etw", "process.start_confirmed_by_etw", now,
              data={"pid": 7, "process_create_time": (now - timedelta(hours=1)).timestamp()}),
    ]
    projection = project_environment_state(events)
    first = rank_environment_state(projection, now=now)
    second = rank_environment_state(projection, now=now)
    assert first == second
    assert first[0]["score"] > 0.8
    assert any("ETW" in reason for reason in first[0]["reasons"])
    assert first[0]["evidence_ids"] == ["start", "etw"]


def test_recency_decays_and_terminal_records_rank_below_active_records():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created = (now - timedelta(hours=1)).timestamp()
    active = event("active", "process.started_observed", now,
                   data={"pid": 1, "create_time": now.timestamp()}, name="active.exe")
    old = event("old", "process.started_observed", now - timedelta(days=3),
                data={"pid": 2, "create_time": created}, name="old.exe")
    stopped = event("stop", "process.stopped_observed", now,
                    data={"pid": 1, "create_time": now.timestamp()}, name="active.exe")
    projection = project_environment_state([active, old, stopped])
    ranked = rank_environment_state(projection, now=now)
    assert ranked[0]["name"] == "old.exe" or ranked[0]["status"] == "running"
    by_name = {row["name"]: row for row in ranked}
    assert by_name["active.exe"]["status"] == "stopped"
    assert by_name["active.exe"]["score"] < 0.9


def test_ranking_limits_and_time_parameters_are_validated():
    projection = project_environment_state([])
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        rank_environment_state(projection, now=now.replace(tzinfo=None))
    with pytest.raises(ValueError):
        rank_environment_state(projection, now=now, limit=0)
    with pytest.raises(ValueError):
        rank_environment_state(projection, now=now, half_life_hours=0)
