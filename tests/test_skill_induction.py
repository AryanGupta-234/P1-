from datetime import datetime, timezone

import pytest

from aie.learning.skills import SkillInductionError, build_skill_candidate, save_skill_candidate
from aie.memory.store import MemoryStore
from aie.orchestration.models import StepRun, TaskRun
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import ActionProposal, CapabilityManifest


def completed_run(*, with_action=False, verified=True):
    if with_action:
        steps = (
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Inspect local metadata.",
                success_criteria="A bounded observation summary exists.",
            ),
            PlanStep(
                step_id="action",
                kind="propose_action",
                description="Request the reviewed Windows Settings action.",
                success_criteria="An approved execution receipt exists.",
                depends_on=("observe",),
                capability_id="windows.settings.open",
            ),
            PlanStep(
                step_id="verify",
                kind="verify",
                description="Check the requested Settings page.",
                success_criteria="The intended page is visible.",
                depends_on=("action",),
            ),
        )
        states = (
            StepRun(step_id="observe", status="completed", summary="Observed local state."),
            StepRun(
                step_id="action",
                status="completed",
                proposal_id="proposal-1",
                summary="A successful execution receipt was recorded.",
            ),
            StepRun(
                step_id="verify",
                status="completed",
                verified=verified,
                summary="User confirmed the postcondition." if verified else "Not confirmed.",
            ),
        )
    else:
        steps = (
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Inspect local metadata.",
                success_criteria="A bounded observation summary exists.",
            ),
            PlanStep(
                step_id="verify",
                kind="verify",
                description="Check the task result.",
                success_criteria="The result is visibly correct.",
                depends_on=("observe",),
            ),
        )
        states = (
            StepRun(step_id="observe", status="completed", summary="Observed local state."),
            StepRun(
                step_id="verify",
                status="completed",
                verified=verified,
                summary="User confirmed the postcondition." if verified else "Not confirmed.",
            ),
        )
    return TaskRun(
        plan=TaskPlan(goal="Complete a safe desktop workflow", steps=steps),
        status="completed",
        steps=states,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def approved_action_ledger(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open a fixed Windows Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allow_autonomous=False,
        allowed_parameters=frozenset(),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    proposal = ActionProposal(
        proposal_id="proposal-1",
        capability_id=manifest.capability_id,
        summary="Open one approved settings page.",
        parameters={},
        source="task-test",
    )
    queue = PolicyProposalQueue(ledger)
    queue.create(proposal, broker)
    queue.review(proposal.proposal_id, approve=True, broker=broker)
    ledger.reserve_execution(proposal.proposal_id)
    ledger.append_execution(proposal.proposal_id,
        status="succeeded",
        action_executed=True,
        verified=False,
        code="test_dispatch",
        summary="Test receipt; postcondition checked separately.",
        elapsed_seconds=0.01,
    )
    return ledger


def test_only_explicitly_verified_completed_runs_produce_candidates():
    candidate = build_skill_candidate(completed_run())
    assert candidate.task_run_id
    assert "Verified postconditions:" in candidate.content
    assert candidate.verified_step_ids == ("verify",)

    with pytest.raises(SkillInductionError, match="positive verification"):
        build_skill_candidate(completed_run(verified=False))


def test_action_based_skill_requires_successful_receipt_and_dependent_verification(tmp_path):
    run = completed_run(with_action=True)
    with pytest.raises(SkillInductionError, match="policy ledger"):
        build_skill_candidate(run)

    ledger = approved_action_ledger(tmp_path)
    candidate = build_skill_candidate(run, policy_ledger=ledger)
    assert candidate.proposal_ids == ("proposal-1",)

    invalid_plan = TaskPlan(
        goal=run.plan.goal,
        steps=(
            run.plan.steps[0],
            run.plan.steps[1],
            run.plan.steps[2].model_copy(update={"depends_on": ()}),
        ),
    )
    invalid_run = run.model_copy(update={"plan": invalid_plan})
    with pytest.raises(SkillInductionError, match="depend on every action"):
        build_skill_candidate(invalid_run, policy_ledger=ledger)


def test_skill_save_requires_existing_completed_task_run_provenance(tmp_path):
    run = completed_run()
    task_store = TaskRunStore(tmp_path / "runs.sqlite3")
    task_store.create(run)
    candidate = build_skill_candidate(run)
    memory_store = MemoryStore(tmp_path / "memory.sqlite3")

    saved = save_skill_candidate(
        candidate,
        memory_store=memory_store,
        task_run_store=task_store,
    )
    assert saved.kind == "procedural"
    assert saved.sensitivity == "sensitive"
    assert saved.source_task_run_ids == [run.run_id]
    assert memory_store.get(saved.memory_id) is not None
    assert memory_store.search("desktop workflow") == []

    forged = candidate.model_copy(update={"content": "A forged unverified procedure."})
    with pytest.raises(SkillInductionError, match="does not match"):
        save_skill_candidate(
            forged,
            memory_store=memory_store,
            task_run_store=task_store,
        )

    internal = candidate.to_memory_record(sensitivity="internal")
    with pytest.raises(ValueError, match="task_run_store is required"):
        memory_store.save(internal)
