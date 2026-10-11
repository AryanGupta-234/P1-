from datetime import datetime

import pytest
from pydantic import ValidationError

from aie.planning import (
    PlanStep,
    PlanValidationError,
    TaskPlan,
    next_ready_steps,
    validate_plan,
)


def step(step_id, *, depends_on=(), kind="observe", capability_id=None):
    return PlanStep(
        step_id=step_id,
        kind=kind,
        description=f"Perform {step_id}",
        success_criteria=f"Confirm {step_id} completed",
        depends_on=list(depends_on),
        capability_id=capability_id,
    )


def test_plan_order_is_stable_and_dependency_aware():
    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect a local application safely",
        steps=[
            step("verify", depends_on=("observe", "reason"), kind="verify"),
            step("observe"),
            step("reason", depends_on=("observe",), kind="reason"),
            step("inform", kind="inform"),
        ],
    )

    report = validate_plan(plan)

    assert report.plan_id == "plan-1"
    assert report.ordered_step_ids == ("observe", "reason", "verify", "inform")


def test_next_ready_steps_requires_explicit_dependency_completion():
    plan = TaskPlan(
        goal="Inspect an application",
        steps=[
            step("observe"),
            step("reason", depends_on=("observe",), kind="reason"),
            step("inform", kind="inform"),
        ],
    )

    assert [item.step_id for item in next_ready_steps(plan)] == ["observe", "inform"]
    assert [
        item.step_id
        for item in next_ready_steps(plan, completed_step_ids={"observe"})
    ] == ["reason", "inform"]


def test_plan_rejects_missing_and_self_dependencies():
    with pytest.raises(ValidationError, match="unknown dependencies"):
        TaskPlan(goal="Bad plan", steps=[step("inspect", depends_on=("missing",))])

    with pytest.raises(ValidationError, match="cannot depend on itself"):
        TaskPlan(goal="Bad plan", steps=[step("inspect", depends_on=("inspect",))])


def test_plan_rejects_cycles():
    plan = TaskPlan(
        goal="Cyclic plan",
        steps=[
            step("first", depends_on=("second",)),
            step("second", depends_on=("first",)),
        ],
    )

    with pytest.raises(PlanValidationError, match="contains a cycle"):
        validate_plan(plan)


def test_plan_rejects_duplicate_ids_and_unknown_completion_ids():
    with pytest.raises(ValidationError, match="duplicate step_id"):
        TaskPlan(goal="Duplicate IDs", steps=[step("same"), step("same")])

    plan = TaskPlan(goal="Simple plan", steps=[step("known")])
    with pytest.raises(ValueError, match="unknown completed step IDs"):
        next_ready_steps(plan, completed_step_ids={"not-in-plan"})


def test_readiness_rejects_completed_steps_with_incomplete_prerequisites():
    plan = TaskPlan(
        goal="Inspect an application",
        steps=[
            step("observe"),
            step("reason", depends_on=("observe",), kind="reason"),
        ],
    )

    with pytest.raises(ValueError, match="incomplete dependencies"):
        next_ready_steps(plan, completed_step_ids={"reason"})


def test_plan_collections_are_immutable_after_validation():
    plan = TaskPlan(goal="Immutable plan", steps=[step("observe")])

    with pytest.raises((AttributeError, TypeError)):
        plan.steps.append(step("extra"))

    with pytest.raises((AttributeError, TypeError)):
        plan.steps[0].depends_on.append("unknown")


def test_action_steps_reference_a_capability_but_do_not_carry_tool_arguments():
    with pytest.raises(ValidationError, match="must reference a capability_id"):
        step("change-setting", kind="propose_action")

    action = step(
        "change-setting",
        kind="propose_action",
        capability_id="windows.display.brightness",
    )
    plan = TaskPlan(goal="Review a setting change", steps=[action])
    assert validate_plan(plan).ordered_step_ids == ("change-setting",)

    with pytest.raises(ValidationError):
        PlanStep(
            step_id="unsafe",
            kind="propose_action",
            description="Run a command",
            success_criteria="Command ran",
            capability_id="windows.display.brightness",
            command="arbitrary shell command",
        )


def test_plan_limits_and_timezone_validation():
    with pytest.raises(ValidationError):
        TaskPlan(goal="Too many steps", steps=[step(f"s{i}") for i in range(26)])

    with pytest.raises(ValidationError, match="timezone-aware"):
        TaskPlan(
            goal="Invalid timestamp",
            steps=[step("one")],
            created_at=datetime(2026, 10, 11),
        )
