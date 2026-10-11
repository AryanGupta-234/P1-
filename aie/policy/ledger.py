"""Append-only local audit ledger for action proposal review and execution.

The ledger records proposals, review outcomes, execution reservations and receipts.
Every transition is appended to the SHA-256 chain; history is never edited.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from aie.policy.models import ActionProposal, PolicyDecision

ProposalStatus = Literal["pending_review", "approved", "rejected", "blocked", "revoked"]
_GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class AuditIntegrityReport:
    valid: bool
    checked_entries: int
    first_invalid_sequence: int | None = None
    reason: str | None = None


def _audit_entry_hash(
    previous_hash: str,
    audit_id: str,
    proposal_id: str,
    event_type: str,
    timestamp: str,
    payload: str,
) -> str:
    canonical = json.dumps(
        [previous_hash, audit_id, proposal_id, event_type, timestamp, payload],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class ProposalSnapshot:
    proposal: ActionProposal
    status: ProposalStatus
    created_at: datetime
    updated_at: datetime
    policy_allowed: bool
    approval_required: bool
    risk_tier: str | None
    reason: str
    reviewer: str | None = None
    action_executed: bool = False
    execution_status: str | None = None
    execution_verified: bool = False
    execution_reserved: bool = False


class PolicyLedger:
    """Append-only SQLite audit trail for policy and execution transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_policy_audit_proposal ON audit_events(proposal_id, sequence)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_policy_audit_timestamp ON audit_events(timestamp)"
            )
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(audit_events)").fetchall()
            }
            if "previous_hash" not in columns or "entry_hash" not in columns:
                db.execute("BEGIN IMMEDIATE")
                try:
                    if "previous_hash" not in columns:
                        db.execute(
                            "ALTER TABLE audit_events ADD COLUMN previous_hash TEXT NOT NULL DEFAULT ''"
                        )
                    if "entry_hash" not in columns:
                        db.execute(
                            "ALTER TABLE audit_events ADD COLUMN entry_hash TEXT NOT NULL DEFAULT ''"
                        )
                    previous = _GENESIS_HASH
                    rows = db.execute(
                        """SELECT sequence, audit_id, proposal_id, event_type, timestamp, payload
                        FROM audit_events ORDER BY sequence ASC"""
                    ).fetchall()
                    for row in rows:
                        entry_hash = _audit_entry_hash(previous, *row[1:])
                        db.execute(
                            "UPDATE audit_events SET previous_hash = ?, entry_hash = ? WHERE sequence = ?",
                            (previous, entry_hash, row[0]),
                        )
                        previous = entry_hash
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise

            db.execute(
                """CREATE TABLE IF NOT EXISTS audit_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            current_head = db.execute(
                "SELECT entry_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            initial_head = current_head[0] if current_head else _GENESIS_HASH
            db.execute(
                "INSERT OR IGNORE INTO audit_meta(key, value) VALUES ('head_hash', ?)",
                (initial_head,),
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _append_row(
        db: sqlite3.Connection,
        *,
        proposal_id: str,
        event_type: str,
        timestamp: datetime,
        payload: dict[str, Any],
    ) -> None:
        previous_row = db.execute(
            "SELECT entry_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous_row[0] if previous_row else _GENESIS_HASH
        audit_id = str(uuid4())
        timestamp_text = timestamp.astimezone(timezone.utc).isoformat()
        payload_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        entry_hash = _audit_entry_hash(
            previous_hash, audit_id, proposal_id, event_type, timestamp_text, payload_text
        )
        db.execute(
            """INSERT INTO audit_events
            (audit_id, proposal_id, event_type, timestamp, payload, previous_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, proposal_id, event_type, timestamp_text, payload_text, previous_hash, entry_hash),
        )
        db.execute(
            """INSERT INTO audit_meta(key, value) VALUES ('head_hash', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (entry_hash,),
        )

    @staticmethod
    def _decision_payload(decision: PolicyDecision) -> dict[str, Any]:
        return {
            "allowed": decision.allowed,
            "approval_required": decision.approval_required,
            "reason": decision.reason,
            "risk_tier": decision.risk_tier,
            "max_execution_seconds": decision.max_execution_seconds,
            "action_executed": False,
        }

    def append_created(
        self,
        proposal: ActionProposal,
        decision: PolicyDecision,
        *,
        initial_status: ProposalStatus,
    ) -> ProposalSnapshot:
        if initial_status not in {"pending_review", "blocked"}:
            raise ValueError("initial proposal status must be pending_review or blocked")
        if decision.proposal_id != proposal.proposal_id:
            raise ValueError("policy decision does not match the proposal ID")
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": 1,
            "proposal": proposal.model_dump(mode="json"),
            "status": initial_status,
            "policy": self._decision_payload(decision),
            "reviewer": None,
            "action_executed": False,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT 1 FROM audit_events WHERE proposal_id = ? LIMIT 1",
                    (proposal.proposal_id,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("proposal ID already exists in the audit ledger")
                self._append_row(
                    db, proposal_id=proposal.proposal_id,
                    event_type="policy.proposal.created", timestamp=now, payload=payload,
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(proposal.proposal_id)  # type: ignore[return-value]

    def append_review(
        self,
        proposal_id: str,
        *,
        status: Literal["approved", "rejected", "blocked"],
        decision: PolicyDecision | None,
        reviewer: str = "local_user",
    ) -> ProposalSnapshot:
        if status not in {"approved", "rejected", "blocked"}:
            raise ValueError("invalid proposal review status")
        now = datetime.now(timezone.utc)
        policy = self._decision_payload(decision) if decision else {
            "allowed": False, "approval_required": False,
            "reason": "Rejected by the local user.", "risk_tier": None,
            "max_execution_seconds": None, "action_executed": False,
        }
        payload = {
            "schema_version": 1, "status": status, "reviewer": reviewer,
            "policy": policy, "action_executed": False,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    """SELECT payload FROM audit_events
                    WHERE proposal_id = ? ORDER BY sequence DESC LIMIT 1""",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("proposal was not found")
                latest = json.loads(row[0])
                if latest.get("status") != "pending_review":
                    raise ValueError("proposal is no longer awaiting review")
                if decision is not None and decision.proposal_id != proposal_id:
                    raise ValueError("policy decision does not match the proposal ID")
                self._append_row(
                    db, proposal_id=proposal_id, event_type="policy.proposal.reviewed",
                    timestamp=now, payload=payload,
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(proposal_id)  # type: ignore[return-value]

    def append_revocation(
        self,
        proposal_id: str,
        *,
        reason: str,
        reviewer: str = "local_user",
    ) -> ProposalSnapshot:
        """Revoke a pending or approved proposal only before execution is reserved."""
        cleaned_reason = " ".join(reason.split())
        if not cleaned_reason or len(cleaned_reason) > 300:
            raise ValueError("revocation reason must contain 1 to 300 characters")
        now = datetime.now(timezone.utc)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    """SELECT payload FROM audit_events
                    WHERE proposal_id = ? ORDER BY sequence ASC""",
                    (proposal_id,),
                ).fetchall()
                if not rows:
                    raise ValueError("proposal was not found")
                latest = json.loads(rows[-1][0])
                if latest.get("status") not in {"pending_review", "approved"}:
                    raise ValueError("only pending or approved proposals can be revoked")
                if any(
                    isinstance(json.loads(row[0]).get("execution"), dict)
                    or json.loads(row[0]).get("execution_reserved") is True
                    for row in rows
                ):
                    raise ValueError("an execution attempt cannot be revoked after it has been reserved")
                policy = latest.get("policy") or {}
                payload = {
                    "schema_version": 1, "status": "revoked", "reviewer": reviewer,
                    "revocation_reason": cleaned_reason,
                    "policy": {
                        "allowed": False, "approval_required": False,
                        "reason": "Revoked by the local user: " + cleaned_reason,
                        "risk_tier": policy.get("risk_tier"),
                        "max_execution_seconds": policy.get("max_execution_seconds"),
                        "action_executed": False,
                    },
                    "action_executed": False,
                }
                self._append_row(
                    db, proposal_id=proposal_id, event_type="policy.proposal.revoked",
                    timestamp=now, payload=payload,
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(proposal_id)  # type: ignore[return-value]

    def get(self, proposal_id: str) -> ProposalSnapshot | None:
        with self._connect() as db:
            rows = db.execute(
                """SELECT event_type, timestamp, payload FROM audit_events
                WHERE proposal_id = ? ORDER BY sequence ASC""",
                (proposal_id,),
            ).fetchall()
        if not rows:
            return None
        created_payload = json.loads(rows[0][2])
        proposal = ActionProposal.model_validate(created_payload["proposal"])
        latest_payload = json.loads(rows[-1][2])
        policy = latest_payload.get("policy") or created_payload.get("policy") or {}
        try:
            status: ProposalStatus = latest_payload["status"]
            created_at = datetime.fromisoformat(rows[0][1])
            updated_at = datetime.fromisoformat(rows[-1][1])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("proposal audit record is malformed") from exc
        execution = next(
            (json.loads(row[2]).get("execution") for row in reversed(rows)
             if isinstance(json.loads(row[2]).get("execution"), dict)),
            None,
        )
        reserved = any(
            json.loads(row[2]).get("execution_reserved") is True for row in rows
        )
        return ProposalSnapshot(
            proposal=proposal, status=status, created_at=created_at, updated_at=updated_at,
            policy_allowed=policy.get("allowed") is True,
            approval_required=policy.get("approval_required") is True,
            risk_tier=policy.get("risk_tier"),
            reason=str(policy.get("reason", "No policy reason recorded.")),
            reviewer=latest_payload.get("reviewer"),
            action_executed=latest_payload.get("action_executed") is True,
            execution_status=execution.get("status") if execution else None,
            execution_verified=execution.get("verified") is True if execution else False,
            execution_reserved=reserved,
        )

    def list(self, *, status: ProposalStatus | None = None, limit: int = 100) -> list[ProposalSnapshot]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT proposal_id FROM audit_events
                WHERE event_type = 'policy.proposal.created'
                ORDER BY sequence DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        result = []
        for (proposal_id,) in rows:
            snapshot = self.get(proposal_id)
            if snapshot is not None and (status is None or snapshot.status == status):
                result.append(snapshot)
        return result

    def reserve_execution(self, proposal_id: str) -> ProposalSnapshot:
        """Atomically reserve a single execution attempt and append the audit event.

        A reservation is a one-time claim. If the process crashes after the claim,
        execution is intentionally blocked for manual inspection; the adapter is not
        automatically retried because its side-effect state may be unknown. Revocation
        and reservation serialize under BEGIN IMMEDIATE, so only one can win.
        """
        now = datetime.now(timezone.utc)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    """SELECT payload FROM audit_events
                    WHERE proposal_id = ? ORDER BY sequence ASC""",
                    (proposal_id,),
                ).fetchall()
                if not rows:
                    raise ValueError("proposal was not found")
                latest = json.loads(rows[-1][0])
                if latest.get("status") != "approved":
                    raise ValueError("only approved proposals may reserve execution")
                if (latest.get("policy") or {}).get("allowed") is not True:
                    raise ValueError("latest policy decision does not authorize execution")
                if any(isinstance(json.loads(row[0]).get("execution"), dict) for row in rows):
                    raise ValueError("proposal already has an execution receipt")
                if any(json.loads(row[0]).get("execution_reserved") is True for row in rows):
                    raise ValueError(
                        "an execution attempt is already reserved; inspect its state before taking further action"
                    )
                if not any(json.loads(row[0]).get("execution_reserved") is True for row in rows):
                    payload = {
                        "schema_version": 1, "status": "approved",
                        "reviewer": latest.get("reviewer"),
                        "policy": latest.get("policy") or {},
                        "action_executed": False,
                        "execution_reserved": True,
                    }
                    self._append_row(
                        db, proposal_id=proposal_id,
                        event_type="policy.proposal.execution_reserved",
                        timestamp=now, payload=payload,
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(proposal_id)  # type: ignore[return-value]

    def append_execution(
        self,
        proposal_id: str,
        *,
        status: Literal["succeeded", "failed"],
        action_executed: bool,
        verified: bool,
        code: str,
        summary: str,
        elapsed_seconds: float,
    ) -> ProposalSnapshot:
        """Append one immutable receipt after the execution reservation exists."""
        if status not in {"succeeded", "failed"}:
            raise ValueError("invalid execution status")
        if verified and not action_executed:
            raise ValueError("an unexecuted action cannot be verified")
        if status == "succeeded" and not action_executed:
            raise ValueError("a successful execution receipt must confirm dispatch")
        if not code or len(code) > 80:
            raise ValueError("execution code must contain 1 to 80 characters")
        if not summary or len(summary) > 300:
            raise ValueError("execution summary must contain 1 to 300 characters")
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        now = datetime.now(timezone.utc)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    """SELECT payload FROM audit_events
                    WHERE proposal_id = ? ORDER BY sequence ASC""",
                    (proposal_id,),
                ).fetchall()
                if not rows:
                    raise ValueError("proposal was not found")
                latest = json.loads(rows[-1][0])
                if latest.get("status") != "approved":
                    raise ValueError("only approved proposals may be executed")
                if not any(json.loads(row[0]).get("execution_reserved") is True for row in rows):
                    raise ValueError("execution must be reserved before a receipt is recorded")
                if any(isinstance(json.loads(row[0]).get("execution"), dict) for row in rows):
                    raise ValueError("proposal already has an execution receipt")
                policy = latest.get("policy") or {}
                if policy.get("allowed") is not True:
                    raise ValueError("latest policy decision does not authorize execution")
                payload = {
                    "schema_version": 1, "status": "approved",
                    "reviewer": latest.get("reviewer"), "policy": policy,
                    "action_executed": bool(action_executed),
                    "execution": {
                        "status": status, "executed": bool(action_executed),
                        "verified": bool(verified), "code": code, "summary": summary,
                        "elapsed_seconds": round(elapsed_seconds, 3),
                    },
                }
                self._append_row(
                    db, proposal_id=proposal_id, event_type="policy.proposal.execution",
                    timestamp=now, payload=payload,
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get(proposal_id)  # type: ignore[return-value]

    def verify_integrity(self) -> AuditIntegrityReport:
        """Verify the global SHA-256 chain and its stored head checkpoint."""
        with self._connect() as db:
            rows = db.execute(
                """SELECT sequence, audit_id, proposal_id, event_type, timestamp, payload,
                    previous_hash, entry_hash
                FROM audit_events ORDER BY sequence ASC"""
            ).fetchall()
        previous = _GENESIS_HASH
        with self._connect() as db:
            stored_head_row = db.execute(
                "SELECT value FROM audit_meta WHERE key = 'head_hash'"
            ).fetchone()
        stored_head = stored_head_row[0] if stored_head_row else _GENESIS_HASH
        for row in rows:
            sequence, audit_id, proposal_id, event_type, timestamp, payload, stored_previous, stored_hash = row
            if not hmac.compare_digest(stored_previous, previous):
                return AuditIntegrityReport(
                    valid=False, checked_entries=len(rows),
                    first_invalid_sequence=sequence,
                    reason="previous-hash link does not match",
                )
            expected = _audit_entry_hash(previous, audit_id, proposal_id, event_type, timestamp, payload)
            if not hmac.compare_digest(stored_hash, expected):
                return AuditIntegrityReport(
                    valid=False, checked_entries=len(rows),
                    first_invalid_sequence=sequence,
                    reason="entry hash does not match the stored payload",
                )
            previous = stored_hash
        if not hmac.compare_digest(previous, stored_head):
            return AuditIntegrityReport(
                valid=False, checked_entries=len(rows),
                first_invalid_sequence=rows[-1][0] if rows else 0,
                reason="stored head checkpoint does not match the ledger tail",
            )
        return AuditIntegrityReport(valid=True, checked_entries=len(rows))

    def audit_trail(self, proposal_id: str) -> list[dict[str, Any]]:
        """Read immutable events for one proposal."""
        with self._connect() as db:
            rows = db.execute(
                """SELECT sequence, audit_id, event_type, timestamp, payload, previous_hash, entry_hash
                FROM audit_events WHERE proposal_id = ? ORDER BY sequence ASC""",
                (proposal_id,),
            ).fetchall()
        return [
            {
                "sequence": row[0], "audit_id": row[1], "event_type": row[2],
                "timestamp": row[3], "payload": json.loads(row[4]),
                "previous_hash": row[5], "entry_hash": row[6],
            }
            for row in rows
        ]


class PolicyProposalQueue:
    """Create and review policy proposals; approval never invokes an executor."""

    def __init__(self, ledger: PolicyLedger) -> None:
        self.ledger = ledger

    def create(self, proposal: ActionProposal, broker) -> ProposalSnapshot:
        decision = broker.evaluate(proposal)
        status: ProposalStatus = (
            "blocked" if not decision.allowed and not decision.approval_required
            else "pending_review"
        )
        return self.ledger.append_created(proposal, decision, initial_status=status)

    def review(
        self,
        proposal_id: str,
        *,
        approve: bool,
        broker,
        reviewer: str = "local_user",
    ) -> ProposalSnapshot:
        current = self.ledger.get(proposal_id)
        if current is None:
            raise ValueError("proposal was not found")
        if current.status != "pending_review":
            raise ValueError("proposal is not awaiting review")
        if not approve:
            return self.ledger.append_review(
                proposal_id, status="rejected", decision=None, reviewer=reviewer
            )
        decision = broker.evaluate(current.proposal, user_approved=True)
        final_status: Literal["approved", "blocked"] = (
            "approved" if decision.allowed else "blocked"
        )
        return self.ledger.append_review(
            proposal_id, status=final_status, decision=decision, reviewer=reviewer
        )
