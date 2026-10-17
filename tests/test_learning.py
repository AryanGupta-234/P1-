from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aie.learning import ExperienceStore


def test_experience_roundtrip_and_normalized_task_key(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    item = store.record("Window Navigation", "Found settings page", "success",
                        evidence_ids=["event-1"], verifier="reviewed-evidence")
    assert item["task_key"] == "window navigation"
    assert store.list_experiences("WINDOW NAVIGATION")[0]["experience_id"] == item["experience_id"]


def test_system_success_requires_evidence(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    with pytest.raises(ValueError):
        store.record("task", "done", "success", verifier="system")


def test_skill_draft_requires_repeated_success_and_evidence(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    for index in range(2):
        store.record("task", f"done {index}", "success", evidence_ids=[f"e{index}"],
                     verifier="reviewed-evidence")
    with pytest.raises(ValueError, match="insufficient"):
        store.create_skill_draft("task", "Reusable task", ["Inspect", "Verify"])
    store.record("task", "done 3", "success", evidence_ids=["e3"], verifier="reviewed-evidence")
    draft = store.create_skill_draft("task", "Reusable task", ["Inspect", "Verify"])
    assert draft["status"] == "pending_review"
    assert len(draft["evidence_ids"]) == 3


def test_skill_draft_requires_some_evidence(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    for index in range(3):
        store.record("task", f"done {index}", "success")
    with pytest.raises(ValueError, match="evidence"):
        store.create_skill_draft("task", "Reusable task", ["Inspect"])


def test_skill_draft_review_is_one_time_and_persistent(tmp_path: Path):
    path = tmp_path / "learning.db"
    store = ExperienceStore(path)
    for index in range(3):
        store.record("task", f"done {index}", "success", evidence_ids=[f"e{index}"])
    draft = store.create_skill_draft("task", "Reusable task", ["Inspect", "Verify"])
    reopened = ExperienceStore(path)
    accepted = reopened.resolve_skill_draft(draft["draft_id"], "accepted")
    assert accepted["status"] == "accepted"
    with pytest.raises(ValueError):
        reopened.resolve_skill_draft(draft["draft_id"], "rejected")


def test_draft_integrity_detection(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    for index in range(3):
        store.record("task", f"done {index}", "success", evidence_ids=[f"e{index}"])
    draft = store.create_skill_draft("task", "Reusable task", ["Inspect"])
    with store._connect() as db:
        db.execute("UPDATE skill_drafts SET steps_json='[\"altered\"]' WHERE draft_id=?",
                   (draft["draft_id"],))
    with pytest.raises(ValueError, match="integrity"):
        store.get_skill_draft(draft["draft_id"])


def test_task_report_excludes_unknown_and_reports_evidence_quality(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    store.record("task", " completed ", "success", evidence_ids=["e1", "e1"],
                 verifier="reviewed-evidence")
    store.record("task", "Completed", "success")
    store.record("task", "partial run", "partial")
    store.record("task", "not completed", "failure")
    store.record("task", "not assessed", "unknown")
    report = store.task_report("TASK")
    assert report["total_experiences"] == 5
    assert report["outcomes"] == {
        "failure": 1, "partial": 1, "success": 2, "unknown": 1,
    }
    assert report["labeled_experiences"] == 4
    assert report["success_rate"] == 0.5
    assert report["success_rate_95pct_wilson"]["lower"] < 0.5
    assert report["success_rate_95pct_wilson"]["upper"] > 0.5
    assert report["successes_with_evidence"] == 1
    assert report["evidence_backed_success_fraction"] == 0.5
    assert report["unique_evidence_references"] == 1
    assert report["repeated_summary_groups"] == 1


def test_task_report_empty_task_has_no_fabricated_rate(tmp_path: Path):
    report = ExperienceStore(tmp_path / "learning.db").task_report("unknown-task")
    assert report["total_experiences"] == 0
    assert report["success_rate"] is None
    assert report["success_rate_95pct_wilson"] is None


@pytest.mark.parametrize("outcome", [["success"], None, 1])
def test_record_rejects_non_string_outcome(tmp_path: Path, outcome):
    with pytest.raises(ValueError, match="outcome"):
        ExperienceStore(tmp_path / "learning.db").record("task", "summary", outcome)


def test_record_rejects_non_list_evidence(tmp_path: Path):
    with pytest.raises(ValueError, match="evidence_ids"):
        ExperienceStore(tmp_path / "learning.db").record(
            "task", "summary", "success", evidence_ids=0
        )


def test_skill_draft_listing_filters_and_verifies_integrity(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    for index in range(3):
        store.record("task", f"success {index}", "success", evidence_ids=[f"e{index}"])
    draft = store.create_skill_draft("task", "Procedure", ["Inspect"])
    assert store.list_skill_drafts(task_key="TASK", status="pending_review")[0]["draft_id"] == draft["draft_id"]
    assert store.list_skill_drafts(status="accepted") == []
    with store._connect() as db:
        db.execute("UPDATE skill_drafts SET title='tampered' WHERE draft_id=?", (draft["draft_id"],))
    with pytest.raises(ValueError, match="integrity"):
        store.list_skill_drafts(task_key="task")


def test_skill_draft_resolution_checks_integrity_before_transition(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    for index in range(3):
        store.record("task", f"success {index}", "success", evidence_ids=[f"e{index}"])
    draft = store.create_skill_draft("task", "Procedure", ["Inspect"])
    with store._connect() as db:
        db.execute("UPDATE skill_drafts SET steps_json='[\"changed\"]' WHERE draft_id=?",
                   (draft["draft_id"],))
    with pytest.raises(ValueError, match="integrity"):
        store.resolve_skill_draft(draft["draft_id"], "accepted")
    with store._connect() as db:
        row = db.execute("SELECT status FROM skill_drafts WHERE draft_id=?",
                         (draft["draft_id"],)).fetchone()
    assert row["status"] == "pending_review"


def test_competing_skill_reviewers_can_only_resolve_once(tmp_path: Path):
    path = tmp_path / "learning.db"
    store = ExperienceStore(path)
    for index in range(3):
        store.record("task", f"success {index}", "success", evidence_ids=[f"e{index}"])
    draft = store.create_skill_draft("task", "Procedure", ["Inspect"])

    def decide(decision: str):
        try:
            result = ExperienceStore(path).resolve_skill_draft(draft["draft_id"], decision)
            return result["status"]
        except ValueError:
            return "already-resolved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["accepted", "rejected"]))
    assert results.count("already-resolved") == 1
    assert sum(item in {"accepted", "rejected"} for item in results) == 1


def _accepted_skill(store: ExperienceStore, title: str = "Reusable procedure"):
    for index in range(3):
        store.record("task", f"success {index}", "success",
                     evidence_ids=[f"source-{index}"], verifier="reviewed-evidence")
    draft = store.create_skill_draft("task", title, ["Inspect", "Verify"])
    store.resolve_skill_draft(draft["draft_id"], "accepted")
    return draft


def test_skill_versions_are_immutable_and_increment(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    first_draft = _accepted_skill(store)
    first = store.publish_skill_draft(first_draft["draft_id"])
    assert first["version"] == 1
    second_draft = _accepted_skill(store)
    second = store.publish_skill_draft(second_draft["draft_id"])
    assert second["skill_id"] == first["skill_id"]
    assert second["version"] == 2
    versions = store.list_skill_versions("TASK", title="Reusable procedure")
    assert [item["version"] for item in versions] == [2, 1]
    with pytest.raises(ValueError, match="already|accepted"):
        store.publish_skill_draft(first_draft["draft_id"])


def test_skill_publish_requires_acceptance_and_checks_digest(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    draft = _accepted_skill(store)
    with store._connect() as db:
        db.execute("UPDATE skill_drafts SET title='tampered' WHERE draft_id=?",
                   (draft["draft_id"],))
    with pytest.raises(ValueError, match="integrity"):
        store.publish_skill_draft(draft["draft_id"])
    assert store.list_skill_versions() == []


def test_skill_regression_evaluation_compares_same_suite_versions(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    first_draft = _accepted_skill(store)
    first = store.publish_skill_draft(first_draft["draft_id"])
    second_draft = _accepted_skill(store)
    second = store.publish_skill_draft(second_draft["draft_id"])

    baseline = store.record_skill_evaluation(
        first["skill_id"], 1, "held-out-settings-v1", trials=10,
        successes=10, partials=0, failures=0, unknown=0,
        evidence_ids=["baseline-report"], evaluator="reviewed-evidence",
    )
    assert baseline["status"] == "baseline_only"
    assert baseline["automation_eligible"] is False

    candidate = store.record_skill_evaluation(
        second["skill_id"], 2, "held-out-settings-v1", trials=10,
        successes=0, partials=0, failures=10, unknown=0,
        evidence_ids=["candidate-report"], evaluator="reviewed-evidence",
    )
    assert candidate["status"] == "regression_observed"
    assert candidate["baseline"]["version"] == 1
    assert candidate["automation_eligible"] is False
    assert len(store.list_skill_evaluations(first["skill_id"])) == 2


def test_skill_evaluation_requires_valid_counts_and_evidence(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    draft = _accepted_skill(store)
    version = store.publish_skill_draft(draft["draft_id"])
    args = (version["skill_id"], 1, "suite")
    with pytest.raises(ValueError, match="sum exactly"):
        store.record_skill_evaluation(
            *args, trials=10, successes=9, partials=0, failures=0, unknown=0,
            evidence_ids=["report"],
        )
    with pytest.raises(ValueError, match="evidence"):
        store.record_skill_evaluation(
            *args, trials=10, successes=10, partials=0, failures=0, unknown=0,
            evidence_ids=[],
        )


def test_skill_evaluation_with_unknown_only_is_insufficient(tmp_path: Path):
    store = ExperienceStore(tmp_path / "learning.db")
    draft = _accepted_skill(store)
    version = store.publish_skill_draft(draft["draft_id"])
    report = store.record_skill_evaluation(
        version["skill_id"], 1, "suite", trials=10, successes=0,
        partials=0, failures=0, unknown=10, evidence_ids=["unknown-outcome-log"],
    )
    assert report["status"] == "insufficient_data"
    assert report["success_rate"] is None
    assert report["automation_eligible"] is False
