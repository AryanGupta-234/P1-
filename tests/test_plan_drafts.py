import sqlite3

import pytest

from aie.goals import GoalStore


def sample_plan():
    return {"steps": [
        {"title": "Inspect architecture", "description": "Review current design.", "depends_on": []},
        {"title": "Implement next slice", "description": "Make a bounded change.", "depends_on": [0]},
    ]}


def test_plan_draft_persists_without_mutating_goal_and_can_be_accepted(tmp_path):
    path = tmp_path / "goals.sqlite3"
    store = GoalStore(path)
    goal = store.create("Improve runtime")
    draft = store.create_plan_draft(goal["goal_id"], sample_plan(), "qwen2.5:3b-instruct")
    assert draft["status"] == "pending_review"
    assert store.get(goal["goal_id"])["progress"]["total"] == 0

    reopened = GoalStore(path)
    assert reopened.get_plan_draft(draft["draft_id"])["plan"] == sample_plan()
    result = reopened.resolve_plan_draft(draft["draft_id"], "accepted")
    assert result["draft"]["status"] == "accepted"
    assert len(result["created_step_ids"]) == 2
    refreshed = reopened.get(goal["goal_id"])
    first, second = refreshed["steps"]
    assert second["dependencies"] == [first["step_id"]]
    assert second["ready"] is False
    assert refreshed["progress"]["total"] == 2
    assert any(item["event_type"] == "plan_draft.accepted" for item in reopened.history(goal["goal_id"]))


def test_rejected_draft_does_not_add_steps_and_cannot_be_resolved_twice(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Review proposal")
    draft = store.create_plan_draft(goal["goal_id"], sample_plan(), "local-model")
    result = store.resolve_plan_draft(draft["draft_id"], "rejected")
    assert result["created_step_ids"] == []
    assert store.get(goal["goal_id"])["progress"]["total"] == 0
    with pytest.raises(ValueError):
        store.resolve_plan_draft(draft["draft_id"], "accepted")


def test_acceptance_requires_active_goal_and_is_atomic(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Paused work")
    draft = store.create_plan_draft(goal["goal_id"], sample_plan(), "local-model")
    store.set_status(goal["goal_id"], "paused")
    with pytest.raises(ValueError):
        store.resolve_plan_draft(draft["draft_id"], "accepted")
    assert store.get(goal["goal_id"])["progress"]["total"] == 0
    assert store.get_plan_draft(draft["draft_id"])["status"] == "pending_review"


def test_plan_draft_integrity_is_verified(tmp_path):
    path = tmp_path / "goals.sqlite3"
    store = GoalStore(path)
    goal = store.create("Integrity")
    draft = store.create_plan_draft(goal["goal_id"], sample_plan(), "local-model")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE goal_plan_drafts SET plan_json=? WHERE draft_id=?",
                   ('{"steps":[]}', draft["draft_id"]))
    with pytest.raises(ValueError, match="integrity"):
        store.get_plan_draft(draft["draft_id"])
    with pytest.raises(ValueError, match="integrity"):
        store.resolve_plan_draft(draft["draft_id"], "accepted")


def test_planner_validation_metadata_is_normalized_before_persistence(tmp_path):
    from aie.planning import validate_plan_output

    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Planner output")
    validated = validate_plan_output(
        '{"steps":[{"title":"One","description":"First","depends_on":[]}]}'
    )
    draft = store.create_plan_draft(goal["goal_id"], validated, "local-model")
    assert draft["plan"] == {
        "steps": [{"title": "One", "description": "First", "depends_on": []}]
    }
