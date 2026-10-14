import json

import pytest

from aie.models.base import ModelResponse
from aie.planning.evaluation import (
    PlanEvaluationDataset,
    PlanEvaluationError,
    evaluate_planner,
    load_plan_evaluation_dataset,
)


def valid_plan(goal, *, capability=False):
    steps = [
        {
            "step_id": "observe",
            "kind": "observe",
            "description": "Inspect bounded local evidence.",
            "success_criteria": "A bounded observation summary exists.",
            "depends_on": [],
        },
        {
            "step_id": "reason",
            "kind": "reason",
            "description": "Reason over that local evidence.",
            "success_criteria": "A concise explanation is recorded.",
            "depends_on": ["observe"],
        },
    ]
    if capability:
        steps.append(
            {
                "step_id": "open-display",
                "kind": "propose_action",
                "description": "Request an explicitly reviewed Settings page.",
                "success_criteria": "A policy proposal exists.",
                "depends_on": ["reason"],
                "capability_id": "windows.settings.open",
            }
        )
    return {"goal": goal, "steps": steps}


class SequenceProvider:
    def __init__(self, payloads, metadata=None):
        self.payloads = list(payloads)
        self.metadata = list(metadata or [])

    def chat(self, request, *, model):
        metadata = self.metadata.pop(0) if self.metadata else {}
        return ModelResponse(
            model=model,
            content=json.dumps(self.payloads.pop(0)),
            elapsed_seconds=metadata.get("elapsed_seconds", 0.01),
            prompt_tokens=metadata.get("prompt_tokens"),
            completion_tokens=metadata.get("completion_tokens"),
            local_inference=metadata.get("local_inference", True),
            provider=metadata.get("provider", "fake-local"),
        )


def test_planner_evaluation_reports_validity_coverage_and_capability_metrics():
    dataset = PlanEvaluationDataset(
        dataset_id="desktop-agent-v1",
        cases=(
            {
                "case_id": "observe-reason",
                "goal": "Inspect desktop playback state",
                "expected_step_kinds": ["observe", "reason"],
            },
            {
                "case_id": "approved-display",
                "goal": "Open a reviewed display settings page",
                "allowed_capability_ids": ["windows.settings.open"],
                "expected_step_kinds": ["observe", "reason", "propose_action"],
                "expected_capability_ids": ["windows.settings.open"],
            },
        ),
    )
    provider = SequenceProvider(
        [
            valid_plan("Inspect desktop playback state"),
            valid_plan("Open a reviewed display settings page", capability=True),
        ]
    )

    report = evaluate_planner(
        dataset,
        provider=provider,
        model="local-test-model",
    )

    assert report.valid_rate == 1.0
    assert report.goal_preservation_rate == 1.0
    assert report.step_kind_coverage == 1.0
    assert report.capability_precision == 1.0
    assert report.capability_recall == 1.0
    assert report.forbidden_capability_rate == 0.0
    assert len(report.cases) == 2


def test_planner_evaluation_counts_invalid_goal_rewrites():
    dataset = PlanEvaluationDataset(
        dataset_id="goal-preservation",
        cases=(
            {
                "case_id": "rewrite",
                "goal": "Inspect desktop playback state",
            },
        ),
    )
    provider = SequenceProvider([valid_plan("A different goal")])

    report = evaluate_planner(dataset, provider=provider, model="local-test-model")

    assert report.valid_rate == 0.0
    assert report.goal_preservation_rate == 0.0
    assert report.cases[0].valid is False
    assert report.cases[0].error_type == "PlanGenerationError"


def test_planner_dataset_loader_rejects_invalid_and_symlink_inputs(tmp_path):
    path = tmp_path / "plan-eval.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "sample",
                "cases": [
                    {
                        "case_id": "one",
                        "goal": "Inspect an application",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_plan_evaluation_dataset(path).dataset_id == "sample"

    invalid = tmp_path / "bad.json"
    invalid.write_text('{"dataset_id":"bad","cases":[]}', encoding="utf-8")
    with pytest.raises(PlanEvaluationError):
        load_plan_evaluation_dataset(invalid)

    link = tmp_path / "linked.json"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(PlanEvaluationError, match="regular local file"):
        load_plan_evaluation_dataset(link)


def test_planner_dataset_rejects_expected_capabilities_outside_allowlist():
    with pytest.raises(ValueError, match="included in the allowlist"):
        PlanEvaluationDataset(
            dataset_id="invalid",
            cases=(
                {
                    "case_id": "one",
                    "goal": "Inspect an app",
                    "expected_capability_ids": ["windows.settings.open"],
                    "allowed_capability_ids": [],
                },
            ),
        )


def test_planner_evaluation_reports_latency_and_only_provider_reported_tokens():
    dataset = PlanEvaluationDataset(
        dataset_id="telemetry",
        cases=(
            {"case_id": "valid", "goal": "Inspect desktop playback state"},
            {"case_id": "invalid", "goal": "Inspect desktop playback state"},
        ),
    )
    provider = SequenceProvider(
        [
            valid_plan("Inspect desktop playback state"),
            valid_plan("A rewritten goal"),
        ],
        metadata=[
            {
                "elapsed_seconds": 0.25,
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "local_inference": True,
                "provider": "ollama",
            },
            {
                "elapsed_seconds": 0.75,
                "completion_tokens": 60,
                "local_inference": False,
                "provider": "openai-compatible",
            },
        ],
    )

    report = evaluate_planner(dataset, provider=provider, model="evaluation-model")

    assert report.valid_rate == 0.5
    assert report.mean_latency_seconds == 0.5
    assert report.p50_latency_seconds == 0.25
    assert report.p95_latency_seconds == 0.75
    assert report.prompt_tokens_total == 120
    assert report.prompt_token_observations == 1
    assert report.completion_tokens_total == 140
    assert report.completion_token_observations == 2
    assert report.local_inference_cases == 1
    assert report.remote_inference_cases == 1
    assert report.cases[0].provider == "ollama"
    assert report.cases[1].valid is False
    assert report.cases[1].elapsed_seconds == 0.75
    assert report.cases[1].prompt_tokens is None
