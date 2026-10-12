import json

import pytest

from aie.memory.evaluation import (
    MemoryEvaluationDataset,
    MemoryEvaluationError,
    evaluate_memory_retrieval,
    load_memory_evaluation_dataset,
)
from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore


class FakeEmbeddingProvider:
    def embed(self, inputs, *, model, timeout_seconds=60.0):
        vectors = []
        for value in inputs:
            lower = value.lower()
            vectors.append(
                [1.0, 0.0, 0.0]
                if "browser" in lower
                else [0.0, 1.0, 0.0]
            )
        return vectors


def test_lexical_evaluation_reports_recall_precision_mrr_and_hit_rate(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    browser = store.save(
        MemoryRecord(
            kind="semantic",
            content="Browser video playback and Edge media troubleshooting.",
            tags=["browser", "video"],
        )
    )
    network = store.save(
        MemoryRecord(
            kind="semantic",
            content="Network DNS connectivity diagnostics.",
            tags=["network", "dns"],
        )
    )
    dataset = MemoryEvaluationDataset(
        dataset_id="retrieval-smoke-v1",
        cases=(
            {
                "case_id": "browser",
                "query": "browser video playback",
                "relevant_memory_ids": [browser.memory_id],
            },
            {
                "case_id": "network",
                "query": "network DNS",
                "relevant_memory_ids": [network.memory_id],
            },
        ),
    )

    report = evaluate_memory_retrieval(dataset, store, k=2)

    assert report.retrieval == "lexical"
    assert report.mean_recall_at_k == 1.0
    assert report.hit_rate_at_k == 1.0
    assert report.mean_reciprocal_rank == 1.0
    assert all(item.precision_at_k == 0.5 for item in report.cases)


def test_semantic_evaluation_uses_explicit_provider_and_model(tmp_path):
    store = MemoryStore(tmp_path / "semantic.sqlite3")
    browser = store.save(
        MemoryRecord(kind="semantic", content="Browser playback memory.")
    )
    network = store.save(
        MemoryRecord(kind="semantic", content="Network diagnostics memory.")
    )
    store.save_embedding(browser.memory_id, "embed-v1", [1.0, 0.0, 0.0])
    store.save_embedding(network.memory_id, "embed-v1", [0.0, 1.0, 0.0])
    dataset = MemoryEvaluationDataset(
        dataset_id="semantic-v1",
        cases=(
            {
                "case_id": "browser",
                "query": "browser playback",
                "relevant_memory_ids": [browser.memory_id],
            },
        ),
    )

    report = evaluate_memory_retrieval(
        dataset,
        store,
        k=1,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model="embed-v1",
    )

    assert report.retrieval == "semantic"
    assert report.embedding_model == "embed-v1"
    assert report.mean_recall_at_k == 1.0


def test_evaluation_rejects_missing_expired_superseded_or_hidden_targets(tmp_path):
    store = MemoryStore(tmp_path / "privacy.sqlite3")
    private = store.save(
        MemoryRecord(
            kind="semantic",
            content="Private browser profile.",
            sensitivity="sensitive",
        )
    )
    dataset = MemoryEvaluationDataset(
        dataset_id="private-v1",
        cases=(
            {
                "case_id": "private",
                "query": "browser profile",
                "relevant_memory_ids": [private.memory_id],
            },
        ),
    )
    with pytest.raises(MemoryEvaluationError, match="sensitivity-filtered"):
        evaluate_memory_retrieval(dataset, store)

    report = evaluate_memory_retrieval(
        dataset, store, include_sensitive=True
    )
    assert report.mean_recall_at_k == 1.0


def test_dataset_loader_rejects_symlink_and_invalid_contract(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "good",
                "cases": [
                    {
                        "case_id": "one",
                        "query": "browser",
                        "relevant_memory_ids": ["memory-1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_memory_evaluation_dataset(path).dataset_id == "good"

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"dataset_id":"bad","cases":[]}', encoding="utf-8")
    with pytest.raises(MemoryEvaluationError):
        load_memory_evaluation_dataset(invalid)

    link = tmp_path / "dataset-link.json"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available for this test environment")
    with pytest.raises(MemoryEvaluationError, match="regular local file"):
        load_memory_evaluation_dataset(link)


def test_evaluation_rejects_invalid_k_and_mismatched_provider_configuration(tmp_path):
    store = MemoryStore(tmp_path / "limits.sqlite3")
    memory = store.save(MemoryRecord(kind="semantic", content="A memory."))
    dataset = MemoryEvaluationDataset(
        dataset_id="limits",
        cases=(
            {
                "case_id": "one",
                "query": "memory",
                "relevant_memory_ids": [memory.memory_id],
            },
        ),
    )
    with pytest.raises(MemoryEvaluationError, match="k must be"):
        evaluate_memory_retrieval(dataset, store, k=0)
    with pytest.raises(MemoryEvaluationError, match="explicit embedding provider"):
        evaluate_memory_retrieval(dataset, store, embedding_model="embed-v1")
