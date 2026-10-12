from pathlib import Path

import pytest

from aie.diagnostics.video_evaluation import (
    TraceDatasetError,
    evaluate_trace_dataset,
    load_trace_dataset,
)


DEFAULT_DATASET = (
    Path(__file__).parents[1]
    / "aie"
    / "diagnostics"
    / "data"
    / "video_traces_v1.json"
)


def test_synthetic_video_trace_corpus_covers_all_rule_causes():
    report = evaluate_trace_dataset(DEFAULT_DATASET)

    assert report.dataset_kind == "synthetic"
    assert report.trace_count == 12
    assert report.exact_match_count == report.trace_count
    assert report.exact_match_rate == 1.0
    assert report.false_positive == 0
    assert report.false_negative == 0
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0
    assert {item.cause for item in report.per_cause} == {
        "network_packet_loss",
        "insufficient_streaming_throughput",
        "stream_buffer_starvation",
        "playback_pipeline_not_advancing_with_buffer",
        "high_network_latency",
        "local_decode_or_render_pressure",
    }


def test_evaluation_serializes_machine_readable_metrics():
    result = evaluate_trace_dataset(DEFAULT_DATASET).as_dict()

    assert result["dataset_name"] == "video-diagnostics-synthetic-v1"
    assert result["micro"]["true_positive"] > 0
    assert len(result["per_cause"]) == 6


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "dataset_name": "bad", "dataset_kind": "synthetic", "cases": []},
        {"schema_version": 1, "dataset_name": "bad", "dataset_kind": "unknown", "cases": [{}]},
        {
            "schema_version": 1,
            "dataset_name": "bad",
            "dataset_kind": "synthetic",
            "cases": [{"id": "one", "metrics": {"playback_stalled": False, "page_text": "no"}, "expected_causes": []}],
        },
        {
            "schema_version": 1,
            "dataset_name": "bad",
            "dataset_kind": "synthetic",
            "cases": [{"id": "one", "metrics": {"playback_stalled": False}, "expected_causes": ["not_a_cause"]}],
        },
    ],
)
def test_rejects_invalid_trace_schema(tmp_path, payload):
    path = tmp_path / "invalid.json"
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TraceDatasetError):
        load_trace_dataset(path)


def test_rejects_duplicate_trace_ids(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":1,"dataset_name":"dup","dataset_kind":"synthetic",'
        '"cases":[{"id":"same","metrics":{"playback_stalled":false},"expected_causes":[]},'
        '{"id":"same","metrics":{"playback_stalled":false},"expected_causes":[]}]}',
        encoding="utf-8",
    )

    with pytest.raises(TraceDatasetError, match="duplicate id"):
        load_trace_dataset(path)
