from __future__ import annotations

import json
from pathlib import Path

import pytest

from aie.prixon.dataset import (
    DatasetValidationError,
    prepare_dataset,
    read_jsonl,
    split_records,
    validate_record,
)


def sample_record(example_id: str, user: str = "Hello", answer: str = "Hi there.") -> dict:
    return {
        "schema_version": 1,
        "id": example_id,
        "category": "conversation_style",
        "source": {
            "name": "Test synthetic data",
            "uri": "",
            "license": "CC0-1.0",
            "attribution": "Test fixture",
            "review_status": "approved",
        },
        "data_classification": "synthetic",
        "user_consent": False,
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_valid_record_normalizes_source_and_messages() -> None:
    result = validate_record(sample_record("one"))
    assert result["id"] == "one"
    assert result["messages"][-1]["role"] == "assistant"


def test_rejects_unreviewed_training_example() -> None:
    row = sample_record("one")
    row["source"]["review_status"] = "pending"
    with pytest.raises(DatasetValidationError, match="approved"):
        validate_record(row)


def test_rejects_private_or_sensitive_classification() -> None:
    row = sample_record("one")
    row["data_classification"] = "private"
    with pytest.raises(DatasetValidationError, match="private and sensitive"):
        validate_record(row)


def test_user_contributed_data_requires_explicit_consent() -> None:
    row = sample_record("one")
    row["data_classification"] = "user_contributed"
    with pytest.raises(DatasetValidationError, match="user_consent"):
        validate_record(row)


def test_rejects_missing_licence() -> None:
    row = sample_record("one")
    row["source"]["license"] = "unknown"
    with pytest.raises(DatasetValidationError, match="approved licence"):
        validate_record(row)


def test_rejects_duplicate_ids_and_duplicate_conversations(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    write_jsonl(path, [sample_record("one"), sample_record("one")])
    with pytest.raises(DatasetValidationError, match="duplicate id"):
        read_jsonl(path)

    write_jsonl(path, [sample_record("one"), sample_record("two")])
    with pytest.raises(DatasetValidationError, match="duplicate conversation"):
        read_jsonl(path)


def test_split_is_deterministic_and_nonempty(tmp_path: Path) -> None:
    records = []
    for index in range(20):
        row = sample_record(f"row-{index}", f"Question {index}", f"Answer {index}")
        from aie.prixon.dataset import validate_record, _canonical_messages
        import hashlib
        item = validate_record(row)
        item["conversation_sha256"] = hashlib.sha256(
            _canonical_messages(item["messages"]).encode("utf-8")
        ).hexdigest()
        records.append(item)

    first = split_records(records, seed=2026)
    second = split_records(records, seed=2026)
    assert {key: [x["id"] for x in value] for key, value in first.items()} == {
        key: [x["id"] for x in value] for key, value in second.items()
    }
    assert all(first[name] for name in ("train", "validation", "test"))
    assert sum(len(value) for value in first.values()) == 20


def test_prepare_creates_manifest_and_refuses_implicit_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    rows = [sample_record(f"row-{i}", f"Question {i}", f"Answer {i}") for i in range(10)]
    write_jsonl(source, rows)
    output = tmp_path / "prepared"

    manifest = prepare_dataset(source, output, seed=7)
    assert manifest["total_examples"] == 10
    assert (output / "train.jsonl").is_file()
    assert (output / "validation.jsonl").is_file()
    assert (output / "test.jsonl").is_file()
    assert (output / "manifest.json").is_file()
    with pytest.raises(FileExistsError):
        prepare_dataset(source, output, seed=7)


def test_requires_three_examples_for_a_three_way_split() -> None:
    records = []
    for index in range(2):
        row = validate_record(sample_record(f"row-{index}", f"Q{index}", f"A{index}"))
        row["conversation_sha256"] = f"hash-{index}"
        records.append(row)
    with pytest.raises(DatasetValidationError, match="at least 3"):
        split_records(records)
