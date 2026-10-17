"""Evidence-gated experience learning and reviewed procedural skill drafts.

This module stores outcomes and proposes reusable procedures. It never executes
skills, edits source code, changes policy, or treats model assertions as proof.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_TASK_KEY = 160
MAX_SUMMARY = 2000
MAX_EVIDENCE = 32
MAX_SKILL_STEPS = 20
MAX_STEP_CHARS = 500
OUTCOMES = {"success", "partial", "failure", "unknown"}
DRAFT_STATES = {"pending_review", "accepted", "rejected"}


class ExperienceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    task_key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_experiences_task
                    ON experiences(task_key, created_at DESC);
                CREATE TABLE IF NOT EXISTS skill_drafts (
                    draft_id TEXT PRIMARY KEY,
                    task_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_drafts_task
                    ON skill_drafts(task_key, status, created_at DESC);
                CREATE TABLE IF NOT EXISTS skill_versions (
                    skill_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    source_draft_id TEXT NOT NULL UNIQUE,
                    task_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(skill_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_skill_versions_task
                    ON skill_versions(task_key, title, version);
                CREATE TABLE IF NOT EXISTS skill_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    suite_key TEXT NOT NULL,
                    trials INTEGER NOT NULL,
                    successes INTEGER NOT NULL,
                    partials INTEGER NOT NULL,
                    failures INTEGER NOT NULL,
                    unknown INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    evaluator TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(skill_id, version) REFERENCES skill_versions(skill_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_skill_evaluations_version
                    ON skill_evaluations(skill_id, version, suite_key, created_at DESC);
                CREATE TABLE IF NOT EXISTS learning_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT,
                    experience_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _task_key(value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TASK_KEY:
            raise ValueError(f"task_key must contain 1..{MAX_TASK_KEY} characters")
        return value.strip().casefold()

    def record(
        self, task_key: str, summary: str, outcome: str, *,
        evidence_ids: list[str] | None = None, verifier: str = "user",
    ) -> dict[str, Any]:
        key = self._task_key(task_key)
        if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY:
            raise ValueError(f"summary must contain 1..{MAX_SUMMARY} characters")
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise ValueError("outcome must be success, partial, failure or unknown")
        if not isinstance(verifier, str) or verifier not in {"user", "system", "reviewed-evidence"}:
            raise ValueError("verifier must be user, system or reviewed-evidence")
        if evidence_ids is None:
            evidence_ids = []
        if not isinstance(evidence_ids, list) or len(evidence_ids) > MAX_EVIDENCE or any(
            not isinstance(item, str) or not item.strip() or len(item) > 128 for item in evidence_ids
        ):
            raise ValueError(f"evidence_ids must contain at most {MAX_EVIDENCE} non-empty IDs")
        # A claimed success without independent evidence is deliberately downgraded.
        if outcome == "success" and verifier != "user" and not evidence_ids:
            raise ValueError("system/evidence-verified success requires evidence IDs")
        record = {
            "experience_id": str(uuid4()), "task_key": key, "summary": summary.strip(),
            "outcome": outcome, "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "verifier": verifier, "created_at": self._now(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO experiences VALUES(?,?,?,?,?,?,?)",
                (record["experience_id"], key, record["summary"], outcome,
                 json.dumps(record["evidence_ids"]), verifier, record["created_at"]),
            )
        return record

    def list_experiences(self, task_key: str, limit: int = 50) -> list[dict[str, Any]]:
        key = self._task_key(task_key)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM experiences WHERE task_key=? ORDER BY created_at DESC, experience_id LIMIT ?",
                (key, limit),
            ).fetchall()
        return [{
            "experience_id": row["experience_id"], "task_key": row["task_key"],
            "summary": row["summary"], "outcome": row["outcome"],
            "evidence_ids": json.loads(row["evidence_json"]),
            "verifier": row["verifier"], "created_at": row["created_at"],
        } for row in rows]

    @staticmethod
    def _wilson_interval(successes: int, trials: int) -> dict[str, float] | None:
        """Return a 95% Wilson score interval; None when there are no trials."""
        if trials <= 0:
            return None
        z = 1.959963984540054
        proportion = successes / trials
        denominator = 1 + z * z / trials
        centre = (proportion + z * z / (2 * trials)) / denominator
        margin = (
            z * ((proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)) ** 0.5)
            / denominator
        )
        return {"lower": max(0.0, centre - margin), "upper": min(1.0, centre + margin)}

    def task_report(self, task_key: str) -> dict[str, Any]:
        """Summarize outcomes without treating unknown or unverified claims as proof."""
        key = self._task_key(task_key)
        with self._connect() as db:
            rows = db.execute(
                """SELECT outcome, verifier, evidence_json, summary, created_at
                   FROM experiences WHERE task_key=? ORDER BY created_at, experience_id""",
                (key,),
            ).fetchall()
        counts = {outcome: 0 for outcome in sorted(OUTCOMES)}
        verifier_counts: dict[str, int] = {}
        evidence_ids: set[str] = set()
        backed_successes = 0
        summary_counts: dict[str, int] = {}
        for row in rows:
            counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
            verifier_counts[row["verifier"]] = verifier_counts.get(row["verifier"], 0) + 1
            ids = json.loads(row["evidence_json"])
            evidence_ids.update(ids)
            if row["outcome"] == "success" and ids:
                backed_successes += 1
            normalized_summary = " ".join(row["summary"].casefold().split())
            summary_counts[normalized_summary] = summary_counts.get(normalized_summary, 0) + 1
        labeled = counts["success"] + counts["partial"] + counts["failure"]
        successes = counts["success"]
        return {
            "task_key": key,
            "total_experiences": len(rows),
            "outcomes": counts,
            "labeled_experiences": labeled,
            "success_rate": successes / labeled if labeled else None,
            "success_rate_95pct_wilson": self._wilson_interval(successes, labeled),
            "successes_with_evidence": backed_successes,
            "evidence_backed_success_fraction": backed_successes / successes if successes else None,
            "unique_evidence_references": len(evidence_ids),
            "verifiers": verifier_counts,
            "repeated_summary_groups": sum(1 for count in summary_counts.values() if count > 1),
            "latest_experience_at": rows[-1]["created_at"] if rows else None,
            "interpretation": (
                "Descriptive history only; small samples and user-reported outcomes are not "
                "independent proof of task reliability. Unknown outcomes are excluded from success rate."
            ),
        }

    def list_skill_drafts(
        self, task_key: str | None = None, status: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if status is not None and (not isinstance(status, str) or status not in DRAFT_STATES):
            raise ValueError("status must be pending_review, accepted or rejected")
        key = self._task_key(task_key) if task_key is not None else None
        clauses, params = [], []
        if key is not None:
            clauses.append("task_key=?")
            params.append(key)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            rows = db.execute(
                "SELECT draft_id FROM skill_drafts" + where +
                " ORDER BY created_at DESC, draft_id LIMIT ?",
                (*params, limit),
            ).fetchall()
        # Re-read through the integrity-checking accessor before exposing content.
        return [draft for row in rows
                if (draft := self.get_skill_draft(row["draft_id"])) is not None]

    def create_skill_draft(
        self, task_key: str, title: str, steps: list[str], *,
        minimum_successes: int = 3,
    ) -> dict[str, Any]:
        key = self._task_key(task_key)
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError("title must contain 1..160 characters")
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_SKILL_STEPS or any(
            not isinstance(step, str) or not step.strip() or len(step) > MAX_STEP_CHARS for step in steps
        ):
            raise ValueError(f"steps must contain 1..{MAX_SKILL_STEPS} non-empty strings of at most {MAX_STEP_CHARS} characters")
        if isinstance(minimum_successes, bool) or not isinstance(minimum_successes, int) or not 2 <= minimum_successes <= 20:
            raise ValueError("minimum_successes must be between 2 and 20")
        with self._connect() as db:
            rows = db.execute(
                """SELECT experience_id,evidence_json,verifier FROM experiences
                   WHERE task_key=? AND outcome='success'
                   ORDER BY created_at DESC LIMIT 100""", (key,)
            ).fetchall()
            if len(rows) < minimum_successes:
                raise ValueError(f"insufficient successful experience: {len(rows)}/{minimum_successes}")
            if not any(row["evidence_json"] != "[]" for row in rows):
                raise ValueError("at least one success must have evidence references")
            evidence = []
            for row in rows:
                evidence.extend(json.loads(row["evidence_json"]))
            evidence = list(dict.fromkeys(evidence))[:MAX_EVIDENCE]
            payload = json.dumps(
                {"task_key": key, "title": title.strip(), "steps": [s.strip() for s in steps],
                 "evidence_ids": evidence},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            now, draft_id = self._now(), str(uuid4())
            db.execute(
                "INSERT INTO skill_drafts VALUES(?,?,?,?,?,?, 'pending_review',?,?)",
                (draft_id, key, title.strip(), json.dumps([s.strip() for s in steps]),
                 json.dumps(evidence), digest, now, now),
            )
            db.execute(
                "INSERT INTO learning_audit(draft_id,event_type,payload_json,occurred_at) VALUES(?,?,?,?)",
                (draft_id, "skill_draft.created",
                 json.dumps({"success_count": len(rows), "evidence_count": len(evidence)}), now),
            )
        return self.get_skill_draft(draft_id)

    def get_skill_draft(self, draft_id: str) -> dict[str, Any] | None:
        if not isinstance(draft_id, str) or not draft_id or len(draft_id) > 64:
            raise ValueError("invalid draft_id")
        with self._connect() as db:
            row = db.execute("SELECT * FROM skill_drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            return None
        result = {
            "draft_id": row["draft_id"], "task_key": row["task_key"], "title": row["title"],
            "steps": json.loads(row["steps_json"]), "evidence_ids": json.loads(row["evidence_json"]),
            "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        payload = json.dumps(
            {"task_key": result["task_key"], "title": result["title"], "steps": result["steps"],
             "evidence_ids": result["evidence_ids"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
            raise ValueError("skill draft integrity check failed")
        return result


    @staticmethod
    def _version_payload(row: sqlite3.Row) -> dict[str, Any]:
        result = {
            "skill_id": row["skill_id"], "version": row["version"],
            "source_draft_id": row["source_draft_id"], "task_key": row["task_key"],
            "title": row["title"], "steps": json.loads(row["steps_json"]),
            "evidence_ids": json.loads(row["evidence_json"]), "created_at": row["created_at"],
        }
        payload = json.dumps(
            {"task_key": result["task_key"], "title": result["title"],
             "steps": result["steps"], "evidence_ids": result["evidence_ids"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
            raise ValueError("skill version integrity check failed")
        return result

    def publish_skill_draft(self, draft_id: str) -> dict[str, Any]:
        """Freeze an accepted draft as an immutable numbered skill version."""
        if not isinstance(draft_id, str) or not draft_id or len(draft_id) > 64:
            raise ValueError("invalid draft_id")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = db.execute("SELECT * FROM skill_drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if draft is None or draft["status"] != "accepted":
                raise ValueError("only an accepted skill draft can be published")
            payload = json.dumps(
                {"task_key": draft["task_key"], "title": draft["title"],
                 "steps": json.loads(draft["steps_json"]),
                 "evidence_ids": json.loads(draft["evidence_json"])},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if digest != draft["payload_sha256"]:
                raise ValueError("skill draft integrity check failed")
            already_published = db.execute(
                "SELECT 1 FROM skill_versions WHERE source_draft_id=?", (draft_id,)
            ).fetchone()
            if already_published is not None:
                raise ValueError("skill draft has already been published")
            existing = db.execute(
                """SELECT skill_id, MAX(version) AS latest FROM skill_versions
                   WHERE task_key=? AND lower(title)=lower(?) GROUP BY skill_id
                   ORDER BY latest DESC LIMIT 1""",
                (draft["task_key"], draft["title"]),
            ).fetchone()
            skill_id = existing["skill_id"] if existing else str(uuid4())
            version = (existing["latest"] + 1) if existing else 1
            now = self._now()
            db.execute(
                "INSERT INTO skill_versions VALUES(?,?,?,?,?,?,?,?,?)",
                (skill_id, version, draft_id, draft["task_key"], draft["title"],
                 draft["steps_json"], draft["evidence_json"], digest, now),
            )
            db.execute(
                "INSERT INTO learning_audit(draft_id,event_type,payload_json,occurred_at) VALUES(?,?,?,?)",
                (draft_id, "skill_version.published",
                 json.dumps({"skill_id": skill_id, "version": version}), now),
            )
            row = db.execute(
                "SELECT * FROM skill_versions WHERE skill_id=? AND version=?",
                (skill_id, version),
            ).fetchone()
            return self._version_payload(row)

    def list_skill_versions(
        self, task_key: str | None = None, title: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        clauses, params = [], []
        if task_key is not None:
            clauses.append("task_key=?")
            params.append(self._task_key(task_key))
        if title is not None:
            if not isinstance(title, str) or not title.strip() or len(title) > 160:
                raise ValueError("title must contain 1..160 characters")
            clauses.append("lower(title)=lower(?)")
            params.append(title.strip())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM skill_versions" + where +
                " ORDER BY task_key, lower(title), version DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._version_payload(row) for row in rows]

    def record_skill_evaluation(
        self, skill_id: str, version: int, suite_key: str, *,
        trials: int, successes: int, partials: int, failures: int, unknown: int,
        evidence_ids: list[str], evaluator: str = "reviewed-evidence",
        minimum_labeled_trials: int = 10, tolerance: float = 0.05,
    ) -> dict[str, Any]:
        if not isinstance(skill_id, str) or not skill_id or len(skill_id) > 64:
            raise ValueError("invalid skill_id")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("version must be a positive integer")
        suite = self._task_key(suite_key)
        counts = (trials, successes, partials, failures, unknown)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("evaluation counts must be non-negative integers")
        if not 1 <= trials <= 10000 or successes + partials + failures + unknown != trials:
            raise ValueError("outcome counts must sum exactly to trials (1..10000)")
        if isinstance(minimum_labeled_trials, bool) or not isinstance(minimum_labeled_trials, int) or not 2 <= minimum_labeled_trials <= 1000:
            raise ValueError("minimum_labeled_trials must be between 2 and 1000")
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 <= tolerance <= 0.25:
            raise ValueError("tolerance must be between 0 and 0.25")
        if not isinstance(evaluator, str) or evaluator not in {"user", "reviewed-evidence"}:
            raise ValueError("evaluator must be user or reviewed-evidence")
        if not isinstance(evidence_ids, list) or not evidence_ids or len(evidence_ids) > MAX_EVIDENCE or any(
            not isinstance(item, str) or not item.strip() or len(item) > 128 for item in evidence_ids
        ):
            raise ValueError("evaluation requires 1..32 evidence references")
        evidence = list(dict.fromkeys(evidence_ids))
        now, evaluation_id = self._now(), str(uuid4())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM skill_versions WHERE skill_id=? AND version=?",
                (skill_id, version),
            ).fetchone()
            if exists is None:
                raise ValueError("skill version not found")
            db.execute(
                "INSERT INTO skill_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (evaluation_id, skill_id, version, suite, trials, successes, partials,
                 failures, unknown, json.dumps(evidence), evaluator, now),
            )
            baseline = db.execute(
                """SELECT * FROM skill_evaluations
                   WHERE skill_id=? AND version<? AND suite_key=?
                   ORDER BY version DESC, created_at DESC LIMIT 1""",
                (skill_id, version, suite),
            ).fetchone()
            candidate_labeled = successes + partials + failures
            candidate_rate = successes / candidate_labeled if candidate_labeled else None
            candidate_failure_rate = failures / candidate_labeled if candidate_labeled else None
            status = "insufficient_data"
            baseline_info = None
            if candidate_labeled >= minimum_labeled_trials and baseline is None:
                status = "baseline_only"
            elif candidate_labeled >= minimum_labeled_trials and baseline is not None:
                base_labeled = baseline["successes"] + baseline["partials"] + baseline["failures"]
                if base_labeled >= minimum_labeled_trials:
                    base_success_rate = baseline["successes"] / base_labeled
                    base_failure_rate = baseline["failures"] / base_labeled
                    baseline_info = {
                        "version": baseline["version"], "labeled_trials": base_labeled,
                        "success_rate": base_success_rate, "failure_rate": base_failure_rate,
                        "success_rate_95pct_wilson": self._wilson_interval(baseline["successes"], base_labeled),
                    }
                    candidate_interval = self._wilson_interval(successes, candidate_labeled)
                    baseline_interval = baseline_info["success_rate_95pct_wilson"]
                    candidate_failure_interval = self._wilson_interval(failures, candidate_labeled)
                    baseline_failure_interval = self._wilson_interval(baseline["failures"], base_labeled)
                    regressed = (
                        candidate_interval["lower"] < baseline_interval["lower"] - tolerance
                        or candidate_failure_interval["upper"] > baseline_failure_interval["upper"] + tolerance
                    )
                    status = "regression_observed" if regressed else "no_regression_observed"
                else:
                    status = "baseline_insufficient_data"
            db.execute(
                "INSERT INTO learning_audit(event_type,payload_json,occurred_at) VALUES(?,?,?)",
                ("skill_evaluation.recorded",
                 json.dumps({"evaluation_id": evaluation_id, "skill_id": skill_id,
                             "version": version, "suite_key": suite, "status": status}),
                 now),
            )
        result = {
            "evaluation_id": evaluation_id, "skill_id": skill_id, "version": version,
            "suite_key": suite, "trials": trials, "labeled_trials": candidate_labeled,
            "successes": successes, "partials": partials, "failures": failures,
            "unknown": unknown, "success_rate": candidate_rate,
            "failure_rate": candidate_failure_rate,
            "success_rate_95pct_wilson": self._wilson_interval(successes, candidate_labeled),
            "baseline": baseline_info, "status": status,
            "automation_eligible": False,
            "interpretation": "Evaluation is evidence-recorded but not an execution grant; human review and separate policy gates remain mandatory.",
            "created_at": now,
        }
        return result

    def list_skill_evaluations(self, skill_id: str, version: int | None = None) -> list[dict[str, Any]]:
        if not isinstance(skill_id, str) or not skill_id or len(skill_id) > 64:
            raise ValueError("invalid skill_id")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 1):
            raise ValueError("version must be a positive integer")
        query = "SELECT * FROM skill_evaluations WHERE skill_id=?"
        params: list[Any] = [skill_id]
        if version is not None:
            query += " AND version=?"
            params.append(version)
        query += " ORDER BY version, suite_key, created_at"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        result = []
        for row in rows:
            labeled = row["successes"] + row["partials"] + row["failures"]
            result.append({
                "evaluation_id": row["evaluation_id"], "skill_id": row["skill_id"],
                "version": row["version"], "suite_key": row["suite_key"],
                "trials": row["trials"], "labeled_trials": labeled,
                "successes": row["successes"], "partials": row["partials"],
                "failures": row["failures"], "unknown": row["unknown"],
                "evidence_ids": json.loads(row["evidence_json"]),
                "success_rate": row["successes"] / labeled if labeled else None,
                "failure_rate": row["failures"] / labeled if labeled else None,
                "evaluator": row["evaluator"], "created_at": row["created_at"],
            })
        return result

    def resolve_skill_draft(self, draft_id: str, decision: str) -> dict[str, Any]:
        if not isinstance(draft_id, str) or not draft_id or len(draft_id) > 64:
            raise ValueError("invalid draft_id")
        if not isinstance(decision, str) or decision not in {"accepted", "rejected"}:
            raise ValueError("decision must be accepted or rejected")
        now = self._now()
        with self._connect() as db:
            # Serialize competing reviewers and validate the exact row in this transaction.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM skill_drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if row is None or row["status"] != "pending_review":
                raise ValueError("pending-review skill draft not found")
            payload = json.dumps(
                {"task_key": row["task_key"], "title": row["title"],
                 "steps": json.loads(row["steps_json"]),
                 "evidence_ids": json.loads(row["evidence_json"])},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
                raise ValueError("skill draft integrity check failed")
            changed = db.execute(
                """UPDATE skill_drafts SET status=?,updated_at=?
                   WHERE draft_id=? AND status='pending_review'""",
                (decision, now, draft_id),
            ).rowcount
            if changed != 1:
                raise ValueError("skill draft was already resolved")
            db.execute(
                "INSERT INTO learning_audit(draft_id,event_type,payload_json,occurred_at) VALUES(?,?,?,?)",
                (draft_id, "skill_draft." + decision, json.dumps({"status": decision}), now),
            )
        return self.get_skill_draft(draft_id) or {}
