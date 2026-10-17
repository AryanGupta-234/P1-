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
