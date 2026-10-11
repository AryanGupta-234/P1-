"""User-confirmed outcomes for diagnostic suggestions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aie.contracts import AIEEvent, EntityRef
from aie.store import EventStore

FeedbackOutcome = Literal["resolved", "not_resolved", "not_attempted"]


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnostic_event_id: str = Field(min_length=1, max_length=80)
    outcome: FeedbackOutcome
    note: str | None = Field(default=None, max_length=1000)


def record_diagnostic_feedback(
    store: EventStore,
    request: FeedbackRequest,
) -> AIEEvent:
    """Persist a feedback event linked to an existing diagnostic finding."""
    target = store.get(request.diagnostic_event_id)
    if target is None:
        raise ValueError("Diagnostic event was not found in the local event store.")
    if target.event_type != "diagnostic.video_finding":
        raise ValueError("Feedback can only reference a video diagnostic finding.")

    cause = target.data.get("cause")
    if not isinstance(cause, str) or not cause:
        cause = target.entity.name

    data = {
        "target_event_id": target.event_id,
        "cause": cause,
        "outcome": request.outcome,
        "action_executed_by_assistant": False,
    }
    sensitivity = "internal"
    if request.note:
        data["user_note"] = request.note
        sensitivity = "sensitive"

    event = AIEEvent(
        timestamp=datetime.now(timezone.utc),
        host_id=target.host_id,
        source="user.feedback",
        event_type="diagnostic.user_feedback",
        entity=EntityRef(type="diagnostic_feedback", name=cause),
        data=data,
        sensitivity=sensitivity,
        confidence=1.0,
        correlation_id=target.event_id,
        evidence_kind="observed",
    )
    store.append(event)
    return event
