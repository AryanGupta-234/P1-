import json

import pytest

from aie.models.base import ModelResponse
from aie.planning.generator import PlanGenerationError, generate_plan


class FakeProvider:
    def __init__(self, content):
        self.content = content
        self.request = None

    def chat(self, request, *, model):
        self.request = request
        return ModelResponse(
            model=model,
            content=self.content,
            elapsed_seconds=0.01,
            local_inference=True,
            provider="fake",
        )


def payload(capability_id=None):
    action = {
        "step_id": "observe",
        "kind": "observe",
        "description": "Inspect a bounded local observation summary.",
        "success_criteria": "A summary is available.",
        "depends_on": [],
    }
    if capability_id:
        action = {
            "step_id": "propose",
            "kind": "propose_action",
            "description": "Open a reviewed settings page.",
            "success_criteria": "A proposal is recorded.",
            "depends_on": ["observe"],
            "capability_id": capability_id,
        }
    return {
        "goal": "Inspect a desktop state",
        "steps": [
            {
                "step_id": "observe",
                "kind": "observe",
                "description": "Inspect local metadata.",
                "success_criteria": "A bounded summary is available.",
                "depends_on": [],
            },
            *([action] if capability_id else []),
        ],
    }


def test_generator_validates_and_preserves_requested_goal():
    provider = FakeProvider(json.dumps(payload()))
    plan = generate_plan(
        "Inspect a desktop state",
        provider=provider,
        model="local-model",
        explicit_context="User-selected context only.",
    )
    assert plan.goal == "Inspect a desktop state"
    assert len(plan.steps) == 1
    assert "User-selected context only." in provider.request.messages[1].content


def test_generator_rejects_capabilities_outside_caller_allowlist():
    provider = FakeProvider(json.dumps(payload("windows.settings.open")))
    with pytest.raises(PlanGenerationError, match="outside the supplied allowlist"):
        generate_plan(
            "Inspect a desktop state",
            provider=provider,
            model="local-model",
            allowed_capability_ids=set(),
        )


def test_generator_rejects_goal_rewriting():
    data = payload()
    data["goal"] = "Different goal"
    provider = FakeProvider(json.dumps(data))
    with pytest.raises(PlanGenerationError, match="changed the requested goal"):
        generate_plan("Inspect a desktop state", provider=provider, model="local-model")
