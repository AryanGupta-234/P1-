"""Strict, dependency-free PRIXON JSONL dataset validation and splitting.

Only reviewed, licensed, non-sensitive examples are accepted. This module is deliberately
independent of Hugging Face so it can run on Windows before data is uploaded to Kaggle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
ALLOWED_ROLES = {"system", "user", "assistant"}
ALLOWED_CLASSIFICATIONS = {"public", "synthetic", "user_contributed"}
INITIAL_TRAINING_CATEGORIES = {
    "identity",
    "conversation_style",
    "contextual_language",
}


class DatasetValidationError(ValueError):
    """Raised when a PRIXON dataset violates its schema or provenance policy."""


def _require_text(value: Any, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetValidationError(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length:
        raise DatasetValidationError(f"{field} exceeds {max_length} characters")
    return value


def _canonical_messages(messages: list[dict[str, str]]) -> str:
    normalized = [
        {"role": item["role"], "content": " ".join(item["content"].casefold().split())}
        for item in messages
    ]
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_record(record: Any, *, require_reviewed: bool = True) -> dict[str, Any]:
    """Validate and normalize one schema-versioned training example."""
    if not isinstance(record, dict):
        raise DatasetValidationError("record must be a JSON object")

    if record.get("schema_version") != SCHEMA_VERSION:
        raise DatasetValidationError(f"schema_version must equal {SCHEMA_VERSION}")

    example_id = _require_text(record.get("id"), "id", max_length=120)
    category = _require_text(record.get("category"), "category", max_length=80).casefold()

    raw_source = record.get("source")
    if not isinstance(raw_source, dict):
        raise DatasetValidationError("source must be an object with provenance and licence")
    source_name = _require_text(raw_source.get("name"), "source.name", max_length=160)
    source_license = _require_text(raw_source.get("license"), "source.license", max_length=80)
    if source_license.casefold() in {"unknown", "none", "noassertion", "unlicensed"}:
        raise DatasetValidationError("source.license must identify an approved licence")
    review_status = _require_text(
        raw_source.get("review_status"), "source.review_status", max_length=24
    ).casefold()
    if require_reviewed and review_status != "approved":
        raise DatasetValidationError("only source.review_status='approved' can enter training")
    source_uri = raw_source.get("uri", "")
    if source_uri is not None and (not isinstance(source_uri, str) or len(source_uri) > 1000):
        raise DatasetValidationError("source.uri must be a string of at most 1000 characters")
    attribution = raw_source.get("attribution", "")
    if attribution is not None and (not isinstance(attribution, str) or len(attribution) > 500):
        raise DatasetValidationError("source.attribution must be a string of at most 500 characters")

    classification = _require_text(
        record.get("data_classification"), "data_classification", max_length=32
    ).casefold()
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise DatasetValidationError(
            "data_classification must be public, synthetic or user_contributed; "
            "private and sensitive records are never accepted"
        )
    if classification == "user_contributed" and record.get("user_consent") is not True:
        raise DatasetValidationError("user_contributed examples require explicit user_consent=true")

    raw_messages = record.get("messages")
    if not isinstance(raw_messages, list) or not 2 <= len(raw_messages) <= 32:
        raise DatasetValidationError("messages must contain between 2 and 32 turns")

    messages: list[dict[str, str]] = []
    user_seen = False
    for index, item in enumerate(raw_messages):
        if not isinstance(item, dict):
            raise DatasetValidationError(f"messages[{index}] must be an object")
        role = item.get("role")
        if role not in ALLOWED_ROLES:
            raise DatasetValidationError(f"messages[{index}].role is unsupported")
        content = _require_text(item.get("content"), f"messages[{index}].content", max_length=16000)
        if role == "user":
            user_seen = True
        messages.append({"role": role, "content": content})

    if not user_seen:
        raise DatasetValidationError("messages must contain at least one user turn")
    if messages[-1]["role"] != "assistant":
        raise DatasetValidationError("the final message must be an assistant response")
    total_chars = sum(len(message["content"]) for message in messages)
    if total_chars > 48_000:
        raise DatasetValidationError("combined message content exceeds 48000 characters")

    return {
        "schema_version": SCHEMA_VERSION,
        "id": example_id,
        "category": category,
        "source": {
            "name": source_name,
            "uri": source_uri or "",
            "license": source_license,
            "attribution": attribution or "",
            "review_status": review_status,
        },
        "data_classification": classification,
        "user_consent": bool(record.get("user_consent", False)),
        "messages": messages,
    }


def read_jsonl(path: str | Path, *, require_reviewed: bool = True) -> list[dict[str, Any]]:
    """Read JSONL, validate every line, and reject duplicate IDs or conversations."""
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"dataset file does not exist: {source_path}")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_conversations: set[str] = set()
    with source_path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                raw_record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise DatasetValidationError(
                    f"{source_path}:{line_number}: invalid JSON: {exc.msg}"
                ) from exc
            try:
                record = validate_record(raw_record, require_reviewed=require_reviewed)
            except DatasetValidationError as exc:
                raise DatasetValidationError(f"{source_path}:{line_number}: {exc}") from exc

            if record["id"] in seen_ids:
                raise DatasetValidationError(f"{source_path}:{line_number}: duplicate id {record['id']!r}")
            seen_ids.add(record["id"])
            fingerprint = hashlib.sha256(
                _canonical_messages(record["messages"]).encode("utf-8")
            ).hexdigest()
            if fingerprint in seen_conversations:
                raise DatasetValidationError(
                    f"{source_path}:{line_number}: duplicate conversation content"
                )
            seen_conversations.add(fingerprint)
            record["conversation_sha256"] = fingerprint
            records.append(record)

    if not records:
        raise DatasetValidationError("dataset contains no non-empty records")
    return records


def split_records(
    records: Iterable[dict[str, Any]],
    *,
    seed: int = 2026,
    train_ratio: float = 0.8,
    validation_ratio: float = 0.1,
) -> dict[str, list[dict[str, Any]]]:
    """Create stable, content-independent train/validation/test partitions."""
    items = list(records)
    if len(items) < 3:
        raise DatasetValidationError("at least 3 unique examples are required for three-way splitting")
    if not 0.0 < train_ratio < 1.0 or not 0.0 < validation_ratio < 1.0:
        raise ValueError("split ratios must be between zero and one")
    test_ratio = 1.0 - train_ratio - validation_ratio
    if test_ratio <= 0:
        raise ValueError("train_ratio + validation_ratio must be less than one")

    ordered = sorted(
        items,
        key=lambda row: hashlib.sha256(
            f"{seed}:{row['id']}:{row['conversation_sha256']}".encode("utf-8")
        ).hexdigest(),
    )
    validation_count = max(1, round(len(ordered) * validation_ratio))
    test_count = max(1, round(len(ordered) * test_ratio))
    train_count = len(ordered) - validation_count - test_count
    if train_count < 1:
        raise DatasetValidationError("not enough examples to keep train, validation and test non-empty")

    return {
        "train": ordered[:train_count],
        "validation": ordered[train_count:train_count + validation_count],
        "test": ordered[train_count + validation_count:],
    }


def _jsonl_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = []
    for record in records:
        clean = {key: value for key, value in record.items() if key != "conversation_sha256"}
        lines.append(json.dumps(clean, ensure_ascii=False, sort_keys=True))
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def prepare_dataset(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 2026,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Validate, split and write JSONL files plus a SHA-256 provenance manifest."""
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError(f"output directory is not empty: {output}; pass --overwrite explicitly")
    records = read_jsonl(source_path)
    splits = split_records(records, seed=seed)

    output.mkdir(parents=True, exist_ok=True)
    split_payloads = {name: _jsonl_bytes(rows) for name, rows in splits.items()}
    split_metadata: dict[str, Any] = {}
    for name, payload in split_payloads.items():
        target = output / f"{name}.jsonl"
        _atomic_write(target, payload)
        split_metadata[name] = {
            "count": len(splits[name]),
            "file": target.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "categories": dict(sorted(Counter(row["category"] for row in splits[name]).items())),
        }

    manifest = {
        "manifest_schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(Path(source_path).name),
        "source_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
        "split_seed": seed,
        "total_examples": len(records),
        "data_classification": "validated; private/sensitive records rejected",
        "initial_training_categories": sorted(INITIAL_TRAINING_CATEGORIES),
        "splits": split_metadata,
        "licences": dict(sorted(Counter(row["source"]["license"] for row in records).items())),
        "review_status": "all examples approved",
        "warning": "Exact duplicates are rejected. Semantic near-duplicates and factual correctness require separate review.",
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(output / "manifest.json", manifest_bytes)
    return manifest


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and prepare PRIXON fine-tuning JSONL data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate a source JSONL dataset")
    validate_parser.add_argument("source")
    validate_parser.add_argument("--allow-unreviewed", action="store_true")

    prepare_parser = subparsers.add_parser("prepare", help="create deterministic train/validation/test splits")
    prepare_parser.add_argument("source")
    prepare_parser.add_argument("output_dir")
    prepare_parser.add_argument("--seed", type=int, default=2026)
    prepare_parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            records = read_jsonl(args.source, require_reviewed=not args.allow_unreviewed)
            report = {
                "valid": True,
                "examples": len(records),
                "categories": dict(sorted(Counter(row["category"] for row in records).items())),
                "initial_training_examples": sum(
                    row["category"] in INITIAL_TRAINING_CATEGORIES for row in records
                ),
            }
        else:
            report = prepare_dataset(
                args.source, args.output_dir, seed=args.seed, overwrite=args.overwrite
            )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (DatasetValidationError, FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"PRIXON dataset error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
