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
