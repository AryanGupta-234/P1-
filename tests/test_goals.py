import pytest

from aie.goals import GoalStore


def test_goal_create_add_steps_dependencies_and_progress(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Build cognitive runtime", "Persistent goal tracking")
    first = store.add_step(goal["goal_id"], "Define state machine")
    second = store.add_step(
        goal["goal_id"], "Implement transitions",
        dependencies=[first["step_id"]],
    )
    assert second["ready"] is False
    assert goal["progress"]["total"] == 0
    store.update_step(goal["goal_id"], first["step_id"], "in_progress")
    store.update_step(goal["goal_id"], first["step_id"], "completed")
    refreshed = store.get(goal["goal_id"])
    assert refreshed["steps_by_id"][second["step_id"]]["ready"] is True
    store.update_step(goal["goal_id"], second["step_id"], "in_progress")
    store.update_step(goal["goal_id"], second["step_id"], "completed")
    assert store.get(goal["goal_id"])["status"] == "completed"


def test_goal_dependency_gate_and_terminal_step(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Goal")
    first = store.add_step(goal["goal_id"], "First")
    second = store.add_step(goal["goal_id"], "Second", dependencies=[first["step_id"]])
    with pytest.raises(ValueError):
        store.update_step(goal["goal_id"], second["step_id"], "in_progress")
    store.update_step(goal["goal_id"], first["step_id"], "completed")
    store.update_step(goal["goal_id"], second["step_id"], "completed")
    with pytest.raises(ValueError):
        store.update_step(goal["goal_id"], second["step_id"], "pending")


def test_goal_rejects_cross_goal_dependencies_and_invalid_input(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    a = store.create("A")
    b = store.create("B")
    a_step = store.add_step(a["goal_id"], "A step")
    with pytest.raises(ValueError):
        store.add_step(b["goal_id"], "Bad dependency", dependencies=[a_step["step_id"]])
    with pytest.raises(ValueError):
        store.create(" ")


def test_goal_pause_resume_and_audit_history(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Pauseable")
    paused = store.set_goal_status(goal["goal_id"], "paused")
    assert paused["status"] == "paused"
    resumed = store.set_goal_status(goal["goal_id"], "active")
    assert resumed["status"] == "active"
    history = store.history(goal["goal_id"])
    assert len(history) == 3
    assert history[-1]["event_type"] == "goal.created"



def test_goal_cannot_be_completed_with_incomplete_steps(tmp_path):
    store = GoalStore(tmp_path / "goals.sqlite3")
    goal = store.create("Must finish")
    step = store.add_step(goal["goal_id"], "Required work")
    with pytest.raises(ValueError):
        store.set_goal_status(goal["goal_id"], "completed")
    store.update_step(goal["goal_id"], step["step_id"], "completed")
    assert store.get(goal["goal_id"])["status"] == "completed"
