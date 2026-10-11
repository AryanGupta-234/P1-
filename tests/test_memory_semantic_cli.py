from typer.testing import CliRunner

from aie import cli
from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore
from aie.models.ollama import OllamaClient


def install_memory_path(tmp_path, monkeypatch):
    path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(cli, "memory_database_path", lambda: path)
    return path


def test_memory_index_cli_indexes_with_local_embedding_provider(tmp_path, monkeypatch):
    path = install_memory_path(tmp_path, monkeypatch)
    store = MemoryStore(path)
    memory = store.save(MemoryRecord(
        kind="semantic",
        content="P1 prefers local semantic retrieval for private memories.",
        tags=["local", "semantic"],
    ))
    calls = []

    def fake_embed(self, inputs, *, model, timeout_seconds=60.0):
        calls.append((inputs, model))
        return [[1.0, 0.0, 0.0] for _ in inputs]

    monkeypatch.setattr(OllamaClient, "embed", fake_embed)
    result = CliRunner().invoke(
        cli.app,
        ["memory-index", "--model", "nomic-embed-text:latest"],
    )

    assert result.exit_code == 0, result.output
    assert "New vectors: 1" in result.output
    assert calls == [(
        ["P1 prefers local semantic retrieval for private memories.\nTags: local, semantic"],
        "nomic-embed-text:latest",
    )]
    assert store.has_embedding(memory.memory_id, "nomic-embed-text:latest")


def test_memory_index_cli_warns_when_sensitive_records_are_included(tmp_path, monkeypatch):
    path = install_memory_path(tmp_path, monkeypatch)
    store = MemoryStore(path)
    secret = store.save(MemoryRecord(
        kind="episodic",
        content="Sensitive local note.",
        sensitivity="sensitive",
    ))
    monkeypatch.setattr(
        OllamaClient,
        "embed",
        lambda self, inputs, *, model, timeout_seconds=60.0: [[0.0, 1.0] for _ in inputs],
    )

    result = CliRunner().invoke(
        cli.app,
        ["memory-index", "--model", "nomic-embed-text:latest", "--include-sensitive"],
    )

    assert result.exit_code == 0, result.output
    assert "Sensitive memory indexing enabled" in result.output
    assert store.has_embedding(secret.memory_id, "nomic-embed-text:latest")


def test_semantic_recall_cli_uses_local_vector_search(tmp_path, monkeypatch):
    path = install_memory_path(tmp_path, monkeypatch)
    store = MemoryStore(path)
    browser_memory = store.save(MemoryRecord(
        kind="semantic",
        content="The preferred browser is Microsoft Edge.",
        tags=["browser", "preference"],
    ))
    store.save_embedding(browser_memory.memory_id, "nomic-embed-text:latest", [1.0, 0.0, 0.0])
    store.save(MemoryRecord(
        kind="episodic",
        content="Network DNS was slow yesterday.",
        tags=["network", "dns"],
    ))
    monkeypatch.setattr(
        OllamaClient,
        "embed",
        lambda self, inputs, *, model, timeout_seconds=60.0: [[0.95, 0.05, 0.0]],
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "recall",
            "Which browser do I use?",
            "--semantic",
            "--embedding-model",
            "nomic-embed-text:latest",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Microsoft Edge" in result.output
    assert browser_memory.memory_id in result.output
