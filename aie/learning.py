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
                CREATE TABLE IF NOT EXISTS experience_fingerprints (
                    experience_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    semantic_key TEXT NOT NULL,
                    FOREIGN KEY(experience_id) REFERENCES experiences(experience_id)
                );
                CREATE INDEX IF NOT EXISTS idx_experience_fingerprints_exact
                    ON experience_fingerprints(fingerprint);
                CREATE INDEX IF NOT EXISTS idx_experience_fingerprints_semantic
                    ON experience_fingerprints(semantic_key);
                CREATE TABLE IF NOT EXISTS experience_links (
                    experience_id TEXT NOT NULL,
                    related_experience_id TEXT NOT NULL,
                    relation TEXT NOT NULL CHECK(relation IN ('duplicate_of','contradicts')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(experience_id, related_experience_id, relation),
                    FOREIGN KEY(experience_id) REFERENCES experiences(experience_id),
                    FOREIGN KEY(related_experience_id) REFERENCES experiences(experience_id)
                );
                CREATE INDEX IF NOT EXISTS idx_experience_links_related
                    ON experience_links(related_experience_id, relation);
                CREATE TABLE IF NOT EXISTS experience_adjudications (
                    adjudication_id TEXT PRIMARY KEY,
                    experience_id TEXT NOT NULL,
                    related_experience_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN (
                        'confirmed_conflict','source_is_correct','related_is_correct',
                        'inconclusive','not_same_claim'
                    )),
                    rationale TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(experience_id,related_experience_id)
                );
                CREATE INDEX IF NOT EXISTS idx_experience_adjudications_created
                    ON experience_adjudications(created_at DESC);
                CREATE TABLE IF NOT EXISTS knowledge_drafts (
                    knowledge_id TEXT PRIMARY KEY,
                    task_key TEXT NOT NULL,
                    normalized_summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending_review','accepted','rejected')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_key, normalized_summary, outcome)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_drafts_status
                    ON knowledge_drafts(status, created_at DESC);
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
            # Backfill fingerprints for pre-existing experiences without modifying them.
            rows = db.execute(
                "SELECT experience_id,task_key,summary,outcome FROM experiences "
                "WHERE experience_id NOT IN (SELECT experience_id FROM experience_fingerprints) "
                "ORDER BY created_at,experience_id"
            ).fetchall()
            for row in rows:
                normalized = " ".join(row["summary"].casefold().split())
                exact = hashlib.sha256(json.dumps(
                    [row["task_key"], normalized, row["outcome"]],
                    ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")).hexdigest()
                semantic = hashlib.sha256(json.dumps(
                    [row["task_key"], normalized],
                    ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")).hexdigest()
                db.execute(
                    "INSERT OR IGNORE INTO experience_fingerprints VALUES(?,?,?)",
                    (row["experience_id"], exact, semantic),
                )


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
        clean_summary = " ".join(summary.casefold().split())
        fingerprint = hashlib.sha256(
            json.dumps([key, clean_summary, outcome], ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        semantic_key = hashlib.sha256(
            json.dumps([key, clean_summary], ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        record = {
            "experience_id": str(uuid4()), "task_key": key, "summary": summary.strip(),
            "outcome": outcome, "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "verifier": verifier, "created_at": self._now(),
            "duplicate_of": None, "contradicts": [],
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior_same = db.execute(
                """SELECT e.experience_id FROM experiences e
                   JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                   WHERE f.fingerprint=? ORDER BY e.created_at, e.experience_id LIMIT 1""",
                (fingerprint,),
            ).fetchone()
            prior_related = db.execute(
                """SELECT e.experience_id,e.outcome FROM experiences e
                   JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                   WHERE f.semantic_key=? ORDER BY e.created_at,e.experience_id""",
                (semantic_key,),
            ).fetchall()
            db.execute(
                "INSERT INTO experiences VALUES(?,?,?,?,?,?,?)",
                (record["experience_id"], key, record["summary"], outcome,
                 json.dumps(record["evidence_ids"]), verifier, record["created_at"]),
            )
            db.execute(
                "INSERT INTO experience_fingerprints VALUES(?,?,?)",
                (record["experience_id"], fingerprint, semantic_key),
            )
            if prior_same is not None:
                record["duplicate_of"] = prior_same["experience_id"]
                db.execute(
                    "INSERT INTO experience_links VALUES(?,?,?,?)",
                    (record["experience_id"], prior_same["experience_id"],
                     "duplicate_of", record["created_at"]),
                )
            for prior in prior_related:
                if prior["outcome"] != outcome and outcome != "unknown" and prior["outcome"] != "unknown":
                    record["contradicts"].append(prior["experience_id"])
                    db.execute(
                        "INSERT INTO experience_links VALUES(?,?,?,?)",
                        (record["experience_id"], prior["experience_id"],
                         "contradicts", record["created_at"]),
                    )
            if record["duplicate_of"] or record["contradicts"]:
                db.execute(
                    "INSERT INTO learning_audit(experience_id,event_type,payload_json,occurred_at) VALUES(?,?,?,?)",
                    (record["experience_id"], "experience.relationships_detected",
                     json.dumps({"duplicate_of": record["duplicate_of"],
                                 "contradicts": record["contradicts"]}), record["created_at"]),
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
            relationship_counts = {
                row["relation"]: row["count"] for row in db.execute(
                    """SELECT l.relation,COUNT(*) AS count FROM experience_links l
                       JOIN experiences e ON e.experience_id=l.experience_id
                       WHERE e.task_key=? GROUP BY l.relation""", (key,)
                ).fetchall()
            }
            conflicted_summaries = db.execute(
                """SELECT COUNT(*) FROM (
                    SELECT f.semantic_key FROM experiences e
                    JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                    WHERE e.task_key=? AND e.outcome IN ('success','partial','failure')
                    GROUP BY f.semantic_key HAVING COUNT(DISTINCT e.outcome)>1
                )""", (key,)
            ).fetchone()[0]
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
            "duplicate_links": relationship_counts.get("duplicate_of", 0),
            "contradiction_links": relationship_counts.get("contradicts", 0),
            "conflicted_summary_groups": conflicted_summaries,
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



    def adjudicate_experience_contradiction(
        self, experience_id: str, related_experience_id: str, decision: str, *,
        rationale: str, evidence_ids: list[str], reviewer: str = "user",
    ) -> dict[str, Any]:
        allowed = {"confirmed_conflict", "source_is_correct", "related_is_correct",
                   "inconclusive", "not_same_claim"}
        for value, label in ((experience_id, "experience_id"),
                             (related_experience_id, "related_experience_id")):
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError(f"invalid {label}")
        if experience_id == related_experience_id:
            raise ValueError("a contradiction must reference two different experiences")
        if not isinstance(decision, str) or decision not in allowed:
            raise ValueError("invalid contradiction decision")
        if not isinstance(rationale, str) or not 8 <= len(rationale.strip()) <= 2000:
            raise ValueError("rationale must contain 8..2000 characters")
        if not isinstance(evidence_ids, list) or not evidence_ids or len(evidence_ids) > MAX_EVIDENCE or any(
            not isinstance(item, str) or not item.strip() or len(item) > 128 for item in evidence_ids
        ):
            raise ValueError("adjudication requires 1..32 evidence references")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 128:
            raise ValueError("reviewer must contain 1..128 characters")
        evidence = list(dict.fromkeys(evidence_ids))
        now, adjudication_id = self._now(), str(uuid4())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            relation = db.execute(
                """SELECT relation FROM experience_links
                   WHERE experience_id=? AND related_experience_id=?""",
                (experience_id, related_experience_id),
            ).fetchone()
            if relation is None or relation["relation"] != "contradicts":
                raise ValueError("the selected experiences do not have a contradiction link")
            inserted = db.execute(
                """INSERT OR IGNORE INTO experience_adjudications
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (adjudication_id, experience_id, related_experience_id, decision,
                 rationale.strip(), json.dumps(evidence), reviewer.strip(), now),
            ).rowcount
            if inserted != 1:
                raise ValueError("this contradiction already has an adjudication")
            db.execute(
                "INSERT INTO learning_audit(event_type,payload_json,occurred_at) VALUES(?,?,?)",
                ("experience.contradiction_adjudicated",
                 json.dumps({"adjudication_id": adjudication_id,
                             "experience_id": experience_id,
                             "related_experience_id": related_experience_id,
                             "decision": decision, "reviewer": reviewer.strip()}), now),
            )
            source = db.execute("SELECT task_key FROM experiences WHERE experience_id=?",
                                 (experience_id,)).fetchone()
        return {
            "adjudication_id": adjudication_id, "experience_id": experience_id,
            "related_experience_id": related_experience_id, "decision": decision,
            "rationale": rationale.strip(), "evidence_ids": evidence,
            "reviewer": reviewer.strip(), "created_at": now,
            "task_key": source["task_key"],
            "source_outcomes_unchanged": True,
        }

    def list_experience_adjudications(self, task_key: str, limit: int = 100) -> list[dict[str, Any]]:
        key = self._task_key(task_key)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as db:
            rows = db.execute(
                """SELECT a.*,e.summary AS source_summary,e.outcome AS source_outcome,
                          r.summary AS related_summary,r.outcome AS related_outcome
                   FROM experience_adjudications a
                   JOIN experiences e ON e.experience_id=a.experience_id
                   JOIN experiences r ON r.experience_id=a.related_experience_id
                   WHERE e.task_key=? ORDER BY a.created_at DESC LIMIT ?""",
                (key, limit),
            ).fetchall()
        return [{
            "adjudication_id": row["adjudication_id"],
            "experience_id": row["experience_id"],
            "related_experience_id": row["related_experience_id"],
            "decision": row["decision"], "rationale": row["rationale"],
            "evidence_ids": json.loads(row["evidence_json"]),
            "reviewer": row["reviewer"], "created_at": row["created_at"],
            "source_summary": row["source_summary"],
            "source_outcome": row["source_outcome"],
            "related_summary": row["related_summary"],
            "related_outcome": row["related_outcome"],
            "source_outcomes_unchanged": True,
        } for row in rows]

    def task_relationships(self, task_key: str, limit: int = 200) -> dict[str, Any]:
        key = self._task_key(task_key)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT l.experience_id,l.related_experience_id,l.relation,l.created_at,
                          a.summary AS source_summary,a.outcome AS source_outcome,
                          b.summary AS related_summary,b.outcome AS related_outcome
                   FROM experience_links l
                   JOIN experiences a ON a.experience_id=l.experience_id
                   JOIN experiences b ON b.experience_id=l.related_experience_id
                   WHERE a.task_key=? ORDER BY l.created_at DESC LIMIT ?""",
                (key, limit),
            ).fetchall()
        return {
            "task_key": key,
            "relationships": [{
                "experience_id": row["experience_id"],
                "related_experience_id": row["related_experience_id"],
                "relation": row["relation"], "created_at": row["created_at"],
                "source_summary": row["source_summary"],
                "source_outcome": row["source_outcome"],
                "related_summary": row["related_summary"],
                "related_outcome": row["related_outcome"],
            } for row in rows],
            "records_preserved": True,
            "interpretation": "Exact normalized-text matches are candidate duplicates; differing non-unknown outcomes for the same normalized task description are contradictions requiring review, not automatic resolution.",
        }

    def create_knowledge_drafts(
        self, task_key: str, *, minimum_repetitions: int = 3, limit: int = 20,
    ) -> list[dict[str, Any]]:
        key = self._task_key(task_key)
        if isinstance(minimum_repetitions, bool) or not isinstance(minimum_repetitions, int) or not 2 <= minimum_repetitions <= 50:
            raise ValueError("minimum_repetitions must be between 2 and 50")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            groups = db.execute(
                """SELECT f.semantic_key,e.summary,e.outcome,COUNT(*) AS repetitions
                   FROM experiences e JOIN experience_fingerprints f
                     ON f.experience_id=e.experience_id
                   WHERE e.task_key=? AND e.outcome IN ('success','partial','failure')
                   GROUP BY f.semantic_key,e.outcome
                   HAVING COUNT(*)>=?
                   ORDER BY repetitions DESC,e.summary LIMIT ?""",
                (key, minimum_repetitions, limit),
            ).fetchall()
            created = []
            for group in groups:
                # Do not consolidate an outcome when the same task description has
                # contradictory non-unknown outcomes; surface it for human review first.
                competing = db.execute(
                    """SELECT COUNT(DISTINCT outcome) FROM experiences e
                       JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                       WHERE e.task_key=? AND f.semantic_key=?
                         AND e.outcome IN ('success','partial','failure')""",
                    (key, group["semantic_key"]),
                ).fetchone()[0]
                if competing > 1:
                    continue
                source_rows = db.execute(
                    """SELECT experience_id,evidence_json,verifier FROM experiences e
                       JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                       WHERE e.task_key=? AND f.semantic_key=? AND e.outcome=?
                       ORDER BY e.created_at,e.experience_id LIMIT 32""",
                    (key, group["semantic_key"], group["outcome"]),
                ).fetchall()
                provenance = [row["experience_id"] for row in source_rows]
                evidence = list(dict.fromkeys(
                    item for row in source_rows for item in json.loads(row["evidence_json"])
                ))[:MAX_EVIDENCE]
                content = group["summary"].strip()
                payload = json.dumps(
                    {"task_key": key, "normalized_summary": group["semantic_key"],
                     "content": content, "outcome": group["outcome"],
                     "provenance_ids": provenance, "evidence_ids": evidence},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                )
                digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                existing = db.execute(
                    """SELECT knowledge_id FROM knowledge_drafts
                       WHERE task_key=? AND normalized_summary=? AND outcome=?""",
                    (key, group["semantic_key"], group["outcome"]),
                ).fetchone()
                if existing:
                    continue
                now, knowledge_id = self._now(), str(uuid4())
                db.execute(
                    "INSERT INTO knowledge_drafts VALUES(?,?,?,?,?,?,?,?,'pending_review',?,?)",
                    (knowledge_id, key, group["semantic_key"], content, group["outcome"],
                     json.dumps(provenance), json.dumps(evidence), digest, now, now),
                )
                db.execute(
                    "INSERT INTO learning_audit(event_type,payload_json,occurred_at) VALUES(?,?,?)",
                    ("knowledge_draft.created",
                     json.dumps({"knowledge_id": knowledge_id, "source_count": len(provenance),
                                 "outcome": group["outcome"]}), now),
                )
                created.append(knowledge_id)
        return [self.get_knowledge_draft(item) for item in created]

    def get_knowledge_draft(self, knowledge_id: str) -> dict[str, Any] | None:
        if not isinstance(knowledge_id, str) or not knowledge_id or len(knowledge_id) > 64:
            raise ValueError("invalid knowledge_id")
        with self._connect() as db:
            row = db.execute("SELECT * FROM knowledge_drafts WHERE knowledge_id=?",
                             (knowledge_id,)).fetchone()
        if row is None:
            return None
        result = {
            "knowledge_id": row["knowledge_id"], "task_key": row["task_key"],
            "content": row["content"], "outcome": row["outcome"],
            "provenance_ids": json.loads(row["provenance_json"]),
            "evidence_ids": json.loads(row["evidence_json"]), "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        payload = json.dumps(
            {"task_key": result["task_key"], "normalized_summary": row["normalized_summary"],
             "content": result["content"], "outcome": result["outcome"],
             "provenance_ids": result["provenance_ids"], "evidence_ids": result["evidence_ids"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
            raise ValueError("knowledge draft integrity check failed")
        return result

    def validate_knowledge_publication(self, knowledge_id: str) -> dict[str, Any]:
        """Recheck an accepted candidate against current evidence immediately before memory import."""
        if not isinstance(knowledge_id, str) or not knowledge_id or len(knowledge_id) > 64:
            raise ValueError("invalid knowledge_id")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM knowledge_drafts WHERE knowledge_id=?",
                             (knowledge_id,)).fetchone()
            if row is None or row["status"] != "accepted":
                raise ValueError("knowledge candidate must be accepted before publication")
            payload = json.dumps(
                {"task_key": row["task_key"], "normalized_summary": row["normalized_summary"],
                 "content": row["content"], "outcome": row["outcome"],
                 "provenance_ids": json.loads(row["provenance_json"]),
                 "evidence_ids": json.loads(row["evidence_json"])},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
                raise ValueError("knowledge draft integrity check failed")
            if row["outcome"] != "success":
                raise ValueError("only successful knowledge can enter semantic memory")
            evidence = json.loads(row["evidence_json"])
            provenance = json.loads(row["provenance_json"])
            if not evidence or len(provenance) < 3 or len(provenance) > 32:
                raise ValueError("publication requires at least three bounded source experiences and evidence")
            conflicts = db.execute(
                """SELECT COUNT(DISTINCT outcome) FROM experiences e
                   JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                   WHERE e.task_key=? AND f.semantic_key=?
                     AND e.outcome IN ('success','partial','failure')""",
                (row["task_key"], row["normalized_summary"]),
            ).fetchone()[0]
            if conflicts != 1:
                raise ValueError("new contradictory outcomes exist; review the knowledge candidate again")
            placeholders = ",".join("?" for _ in provenance)
            sources = db.execute(
                f"""SELECT e.experience_id,e.evidence_json FROM experiences e
                    JOIN experience_fingerprints f ON f.experience_id=e.experience_id
                    WHERE e.task_key=? AND e.outcome='success' AND f.semantic_key=?
                      AND e.experience_id IN ({placeholders})""",
                (row["task_key"], row["normalized_summary"], *provenance),
            ).fetchall()
            if len(sources) != len(provenance):
                raise ValueError("knowledge provenance no longer matches successful source experiences")
            available_evidence = {
                item for source in sources for item in json.loads(source["evidence_json"])
            }
            if not set(evidence).issubset(available_evidence):
                raise ValueError("knowledge evidence references do not match source experiences")
        return self.get_knowledge_draft(knowledge_id) or {}

    def resolve_knowledge_draft(self, knowledge_id: str, decision: str) -> dict[str, Any]:
        if not isinstance(knowledge_id, str) or not knowledge_id or len(knowledge_id) > 64:
            raise ValueError("invalid knowledge_id")
        if not isinstance(decision, str) or decision not in {"accepted", "rejected"}:
            raise ValueError("decision must be accepted or rejected")
        now = self._now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM knowledge_drafts WHERE knowledge_id=?",
                             (knowledge_id,)).fetchone()
            if row is None or row["status"] != "pending_review":
                raise ValueError("pending-review knowledge draft not found")
            payload = json.dumps(
                {"task_key": row["task_key"], "normalized_summary": row["normalized_summary"],
                 "content": row["content"], "outcome": row["outcome"],
                 "provenance_ids": json.loads(row["provenance_json"]),
                 "evidence_ids": json.loads(row["evidence_json"])},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
                raise ValueError("knowledge draft integrity check failed")
            changed = db.execute(
                "UPDATE knowledge_drafts SET status=?,updated_at=? "
                "WHERE knowledge_id=? AND status='pending_review'",
                (decision, now, knowledge_id),
            ).rowcount
            if changed != 1:
                raise ValueError("knowledge draft already resolved")
            db.execute(
                "INSERT INTO learning_audit(event_type,payload_json,occurred_at) VALUES(?,?,?)",
                ("knowledge_draft." + decision,
                 json.dumps({"knowledge_id": knowledge_id}), now),
            )
        return self.get_knowledge_draft(knowledge_id) or {}

    def list_knowledge_drafts(
        self, task_key: str | None = None, status: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if status is not None and (not isinstance(status, str) or status not in DRAFT_STATES):
            raise ValueError("invalid knowledge draft status")
        clauses, params = [], []
        if task_key is not None:
            clauses.append("task_key=?")
            params.append(self._task_key(task_key))
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            rows = db.execute(
                "SELECT knowledge_id FROM knowledge_drafts" + where +
                " ORDER BY created_at DESC,knowledge_id LIMIT ?", (*params, limit)
            ).fetchall()
        return [self.get_knowledge_draft(row["knowledge_id"]) for row in rows]

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
