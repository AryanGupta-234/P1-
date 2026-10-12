"""Deterministic evaluation of the rule-based video diagnostic pipeline.

The bundled corpus is synthetic regression data, not a representative field sample.
Its metrics detect code regressions; they must not be presented as calibrated
real-world accuracy or probability estimates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aie.diagnostics.video_buffering import VideoMetrics, diagnose_video_buffering

MAX_TRACE_CASES = 2000
KNOWN_CAUSES = frozenset({
    "network_packet_loss",
    "insufficient_streaming_throughput",
    "stream_buffer_starvation",
    "playback_pipeline_not_advancing_with_buffer",
    "high_network_latency",
    "local_decode_or_render_pressure",
})
_ALLOWED_METRIC_FIELDS = frozenset(VideoMetrics.__dataclass_fields__)


class TraceDatasetError(ValueError):
    """The trace corpus does not satisfy the evaluation schema."""


@dataclass(frozen=True, slots=True)
class CauseScore:
    cause: str
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float | None
    recall: float | None
    f1: float | None


@dataclass(frozen=True, slots=True)
class TraceEvaluation:
    dataset_name: str
    dataset_kind: str
    trace_count: int
    exact_match_count: int
    exact_match_rate: float
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float | None
    recall: float | None
    f1: float | None
    per_cause: tuple[CauseScore, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "dataset_kind": self.dataset_kind,
            "trace_count": self.trace_count,
            "exact_match_count": self.exact_match_count,
            "exact_match_rate": self.exact_match_rate,
            "micro": {
                "true_positive": self.true_positive,
                "false_positive": self.false_positive,
                "false_negative": self.false_negative,
                "precision": self.precision,
                "recall": self.recall,
                "f1": self.f1,
            },
            "per_cause": [
                {
                    "cause": item.cause,
                    "true_positive": item.true_positive,
                    "false_positive": item.false_positive,
                    "false_negative": item.false_negative,
                    "true_negative": item.true_negative,
                    "precision": item.precision,
                    "recall": item.recall,
                    "f1": item.f1,
                }
                for item in self.per_cause
            ],
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 4)


def load_trace_dataset(path: Path) -> tuple[str, str, list[tuple[VideoMetrics, frozenset[str]]]]:
    """Load and strictly validate a versioned JSON trace corpus."""
    try:
        if path.stat().st_size > 5 * 1024 * 1024:
            raise TraceDatasetError("trace dataset exceeds the 5 MiB size limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except TraceDatasetError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TraceDatasetError(f"could not read trace dataset: {type(exc).__name__}") from exc
    if (
        not isinstance(payload, dict)
        or isinstance(payload.get("schema_version"), bool)
        or payload.get("schema_version") != 1
    ):
        raise TraceDatasetError("trace dataset must be an object with schema_version=1")
    name = payload.get("dataset_name")
    kind = payload.get("dataset_kind")
    cases = payload.get("cases")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise TraceDatasetError("dataset_name must be a non-empty string up to 100 characters")
    if not isinstance(kind, str) or kind not in {"synthetic", "field"}:
        raise TraceDatasetError("dataset_kind must be 'synthetic' or 'field'")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_TRACE_CASES:
        raise TraceDatasetError(f"cases must contain between 1 and {MAX_TRACE_CASES} traces")

    seen_ids: set[str] = set()
    parsed: list[tuple[VideoMetrics, frozenset[str]]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise TraceDatasetError(f"case {index} must be an object")
        case_id = case.get("id")
        metrics = case.get("metrics")
        expected = case.get("expected_causes")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen_ids:
            raise TraceDatasetError(f"case {index} has a missing or duplicate id")
        seen_ids.add(case_id)
        if not isinstance(metrics, dict):
            raise TraceDatasetError(f"case {case_id} metrics must be an object")
        extra = set(metrics) - _ALLOWED_METRIC_FIELDS
        if extra:
            raise TraceDatasetError(f"case {case_id} has unsupported metrics: {', '.join(sorted(extra))}")
        if not isinstance(expected, list) or any(
            not isinstance(item, str) or item not in KNOWN_CAUSES for item in expected
        ):
            raise TraceDatasetError(f"case {case_id} expected_causes contains an unknown cause")
        if len(set(expected)) != len(expected):
            raise TraceDatasetError(f"case {case_id} expected_causes contains duplicates")
        try:
            parsed.append((VideoMetrics(**metrics), frozenset(expected)))
        except (TypeError, ValueError) as exc:
            raise TraceDatasetError(f"case {case_id} has invalid metrics: {exc}") from exc
    return name.strip(), kind, parsed


def evaluate_trace_dataset(path: Path) -> TraceEvaluation:
    """Evaluate predicted cause sets against the trace corpus ground truth."""
    name, kind, traces = load_trace_dataset(path)
    counts: dict[str, list[int]] = {
        cause: [0, 0, 0, 0] for cause in sorted(KNOWN_CAUSES)
    }  # TP, FP, FN, TN
    exact_matches = 0
    micro_tp = micro_fp = micro_fn = 0

    for metrics, expected in traces:
        predicted = frozenset(item.cause for item in diagnose_video_buffering(metrics).findings)
        if predicted == expected:
            exact_matches += 1
        for cause, values in counts.items():
            actual_positive = cause in expected
            predicted_positive = cause in predicted
            if actual_positive and predicted_positive:
                values[0] += 1
                micro_tp += 1
            elif not actual_positive and predicted_positive:
                values[1] += 1
                micro_fp += 1
            elif actual_positive and not predicted_positive:
                values[2] += 1
                micro_fn += 1
            else:
                values[3] += 1

    cause_scores: list[CauseScore] = []
    for cause, values in counts.items():
        tp, fp, fn, tn = values
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        cause_scores.append(CauseScore(
            cause, tp, fp, fn, tn, precision, recall, _f1(precision, recall)
        ))
    precision = _ratio(micro_tp, micro_tp + micro_fp)
    recall = _ratio(micro_tp, micro_tp + micro_fn)
    return TraceEvaluation(
        dataset_name=name,
        dataset_kind=kind,
        trace_count=len(traces),
        exact_match_count=exact_matches,
        exact_match_rate=round(exact_matches / len(traces), 4),
        true_positive=micro_tp,
        false_positive=micro_fp,
        false_negative=micro_fn,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        per_cause=tuple(cause_scores),
    )
