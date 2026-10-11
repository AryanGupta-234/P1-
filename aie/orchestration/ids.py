"""Stable identifiers for task-derived policy artifacts."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


def proposal_id_for_task_step(run_id: str, step_id: str) -> str:
    """Derive one stable proposal ID for a task run/step pair."""
    if not run_id or not step_id:
        raise ValueError("run_id and step_id are required")
    return str(uuid5(NAMESPACE_URL, f"aie-task-proposal:{run_id}:{step_id}"))
