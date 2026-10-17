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
