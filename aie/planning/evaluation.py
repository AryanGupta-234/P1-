"""Reproducible evaluation for model-drafted declarative task plans."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aie.models.base import ModelResponse
from aie.planning.generator import PlanGenerationError, generate_plan
from aie.planning.models import StepKind
from aie.planning.validator import PlanValidationError


class PlanEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    allowed_capability_ids: tuple[str, ...] = Field(default=(), max_length=50)
    expected_step_kinds: tuple[StepKind, ...] = Field(default=(), max_length=5)
    expected_capability_ids: tuple[str, ...] = Field(default=(), max_length=50)
    forbidden_capability_ids: tuple[str, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_expectations(self) -> "PlanEvaluationCase":
        if len(set(self.allowed_capability_ids)) != len(self.allowed_capability_ids):
            raise ValueError("allowed capability IDs must be unique")
        if len(set(self.expected_capability_ids)) != len(self.expected_capability_ids):
            raise ValueError("expected capability IDs must be unique")
        if len(set(self.forbidden_capability_ids)) != len(self.forbidden_capability_ids):
            raise ValueError("forbidden capability IDs must be unique")
        if not set(self.expected_capability_ids).issubset(self.allowed_capability_ids):
            raise ValueError("expected capability IDs must be included in the allowlist")
        if set(self.expected_capability_ids) & set(self.forbidden_capability_ids):
            raise ValueError("a capability cannot be both expected and forbidden")
        return self


class PlanEvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    cases: tuple[PlanEvaluationCase, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> "PlanEvaluationDataset":
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("plan evaluation case IDs must be unique")
        return self


class PlanEvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    valid: bool
    goal_preserved: bool
    required_step_kinds_found: int
    required_step_kind_count: int
    expected_capabilities_found: int
    expected_capability_count: int
    forbidden_capabilities_found: int
    actual_capability_ids: tuple[str, ...]
    elapsed_seconds: float | None = Field(default=None, ge=0.0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    local_inference: bool | None = None
    provider: str | None = None
    error_type: str | None = None


class PlanEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    model: str
    cases: tuple[PlanEvaluationCaseResult, ...]
    valid_rate: float
    goal_preservation_rate: float
    step_kind_coverage: float
    capability_precision: float
    capability_recall: float
    forbidden_capability_rate: float
    mean_latency_seconds: float | None
    p50_latency_seconds: float | None
    p95_latency_seconds: float | None
    prompt_tokens_total: int | None
    prompt_token_observations: int
    completion_tokens_total: int | None
    completion_token_observations: int
    local_inference_cases: int
    remote_inference_cases: int
    evaluated_at_utc: str


class PlanEvaluationError(ValueError):
    """Raised when the benchmark dataset or provider configuration is invalid."""


def load_plan_evaluation_dataset(path: Path) -> PlanEvaluationDataset:
    if path.is_symlink() or not path.is_file():
        raise PlanEvaluationError("dataset path must be a regular local file")
    if path.stat().st_size > 256 * 1024:
        raise PlanEvaluationError("dataset exceeds 256 KiB")
    try:
        return PlanEvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PlanEvaluationError(
            f"dataset could not be validated ({type(exc).__name__})"
        ) from exc


class _ResponseCapture:
    """Capture provider-reported metadata without retaining prompt or response text."""

    def __init__(self, provider) -> None:
        self.provider = provider
        self.response: ModelResponse | None = None

    def chat(self, request, *, model: str) -> ModelResponse:
        response = self.provider.chat(request, model=model)
        self.response = response
        return response


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate_planner(
    dataset: PlanEvaluationDataset,
    *,
    provider,
    model: str,
) -> PlanEvaluationReport:
    """Measure validated plan contracts over a fixed dataset; never mutates a model."""
    if not model or len(model) > 200:
        raise PlanEvaluationError("model name must contain 1 to 200 characters")

    rows: list[PlanEvaluationCaseResult] = []
    valid_total = 0
    goal_total = 0
    required_kinds_total = 0
    required_kinds_found = 0
    expected_caps_total = 0
    expected_caps_found = 0
    forbidden_found = 0
    actual_caps_total = 0
    latency_values: list[float] = []
    prompt_token_values: list[int] = []
    completion_token_values: list[int] = []
    local_inference_cases = 0
    remote_inference_cases = 0

    for case in dataset.cases:
        capture = _ResponseCapture(provider)
        try:
            plan = generate_plan(
                case.goal,
                provider=capture,
                model=model,
                allowed_capability_ids=set(case.allowed_capability_ids),
            )
            response = capture.response
            if response is not None:
                latency_values.append(response.elapsed_seconds)
                if response.prompt_tokens is not None:
                    prompt_token_values.append(response.prompt_tokens)
                if response.completion_tokens is not None:
                    completion_token_values.append(response.completion_tokens)
                if response.local_inference:
                    local_inference_cases += 1
                else:
                    remote_inference_cases += 1
            actual_caps = {
                step.capability_id for step in plan.steps
                if step.capability_id is not None
            }
            actual_kinds = {step.kind for step in plan.steps}
            expected_kinds = set(case.expected_step_kinds)
            expected_caps = set(case.expected_capability_ids)
            forbidden_caps = set(case.forbidden_capability_ids)
            kind_found = len(actual_kinds & expected_kinds)
            cap_found = len(actual_caps & expected_caps)
            forbidden_count = len(actual_caps & forbidden_caps)
            valid_total += 1
            goal_total += plan.goal == case.goal
            required_kinds_total += len(expected_kinds)
            required_kinds_found += kind_found
            expected_caps_total += len(expected_caps)
            expected_caps_found += cap_found
            actual_caps_total += len(actual_caps)
            forbidden_found += forbidden_count
            rows.append(
                PlanEvaluationCaseResult(
                    case_id=case.case_id,
                    valid=True,
                    goal_preserved=plan.goal == case.goal,
                    required_step_kinds_found=kind_found,
                    required_step_kind_count=len(expected_kinds),
                    expected_capabilities_found=cap_found,
                    expected_capability_count=len(expected_caps),
                    forbidden_capabilities_found=forbidden_count,
                    actual_capability_ids=tuple(sorted(actual_caps)),
                    elapsed_seconds=response.elapsed_seconds if response else None,
                    prompt_tokens=response.prompt_tokens if response else None,
                    completion_tokens=response.completion_tokens if response else None,
                    local_inference=response.local_inference if response else None,
                    provider=response.provider if response else None,
                )
            )
        except (PlanGenerationError, PlanValidationError, ValueError) as exc:
            response = capture.response
            if response is not None:
                latency_values.append(response.elapsed_seconds)
                if response.prompt_tokens is not None:
                    prompt_token_values.append(response.prompt_tokens)
                if response.completion_tokens is not None:
                    completion_token_values.append(response.completion_tokens)
                if response.local_inference:
                    local_inference_cases += 1
                else:
                    remote_inference_cases += 1
            rows.append(
                PlanEvaluationCaseResult(
                    case_id=case.case_id,
                    valid=False,
                    goal_preserved=False,
                    required_step_kinds_found=0,
                    required_step_kind_count=len(case.expected_step_kinds),
                    expected_capabilities_found=0,
                    expected_capability_count=len(case.expected_capability_ids),
                    forbidden_capabilities_found=0,
                    actual_capability_ids=(),
                    elapsed_seconds=response.elapsed_seconds if response else None,
                    prompt_tokens=response.prompt_tokens if response else None,
                    completion_tokens=response.completion_tokens if response else None,
                    local_inference=response.local_inference if response else None,
                    provider=response.provider if response else None,
                    error_type=type(exc).__name__,
                )
            )
            required_kinds_total += len(case.expected_step_kinds)
            expected_caps_total += len(case.expected_capability_ids)

    case_count = len(rows)
    valid = valid_total / case_count
    goal_rate = goal_total / case_count
    kind_coverage = (
        required_kinds_found / required_kinds_total if required_kinds_total else 1.0
    )
    cap_precision = (
        expected_caps_found / actual_caps_total if actual_caps_total else (
            1.0 if expected_caps_total == 0 else 0.0
        )
    )
    cap_recall = (
        expected_caps_found / expected_caps_total if expected_caps_total else 1.0
    )
    forbidden_rate = (
        forbidden_found / actual_caps_total if actual_caps_total else 0.0
    )
    return PlanEvaluationReport(
        dataset_id=dataset.dataset_id,
        model=model,
        cases=tuple(rows),
        valid_rate=valid,
        goal_preservation_rate=goal_rate,
        step_kind_coverage=kind_coverage,
        capability_precision=cap_precision,
        capability_recall=cap_recall,
        forbidden_capability_rate=forbidden_rate,
        mean_latency_seconds=(
            sum(latency_values) / len(latency_values) if latency_values else None
        ),
        p50_latency_seconds=_percentile(latency_values, 0.50),
        p95_latency_seconds=_percentile(latency_values, 0.95),
        prompt_tokens_total=(
            sum(prompt_token_values) if prompt_token_values else None
        ),
        prompt_token_observations=len(prompt_token_values),
        completion_tokens_total=(
            sum(completion_token_values) if completion_token_values else None
        ),
        completion_token_observations=len(completion_token_values),
        local_inference_cases=local_inference_cases,
        remote_inference_cases=remote_inference_cases,
        evaluated_at_utc=datetime.now(timezone.utc).isoformat(),
    )
