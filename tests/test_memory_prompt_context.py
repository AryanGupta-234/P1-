import pytest

from aie.memory.models import MemoryRecord
from aie.memory.prompt_context import build_memory_prompt_context
from aie.memory.store import MemoryStore


def test_memory_prompt_context_is_bounded_and_explicitly_quoted(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    memory = store.save(MemoryRecord(
        kind="semantic",
        content="P1 uses a local Ollama model for private reasoning.",
        tags=["ollama", "local"],
    ))

    result = build_memory_prompt_context(
        "Explain the Ollama reasoning design.",
        store,
        limit=5,
        max_characters=1500,
    )

    assert result.memory_ids == (memory.memory_id,)
    assert memory.content in result.content
    assert "untrusted reference data" in result.content.lower()


def test_sensitive_memories_are_not_attached_unless_explicitly_requested(tmp_path):
    store = MemoryStore(tmp_path / "sensitive.sqlite3")
    secret = store.save(MemoryRecord(
        kind="episodic",
        content="Private user-specific note.",
        sensitivity="sensitive",
        tags=["private", "user"],
    ))

    default_result = build_memory_prompt_context("private user note", store)
    explicit_result = build_memory_prompt_context(
        "private user note",
        store,
        include_sensitive=True,
    )

    assert default_result.content == ""
    assert default_result.memory_ids == ()
    assert explicit_result.memory_ids == (secret.memory_id,)


def test_memory_prompt_context_respects_total_and_per_record_budgets(tmp_path):
    store = MemoryStore(tmp_path / "bounded.sqlite3")
    store.save(MemoryRecord(
        kind="semantic",
        content="python " * 200,
        tags=["python"],
    ))

    result = build_memory_prompt_context(
        "python",
        store,
        max_characters=800,
        per_record_characters=150,
    )

    assert len(result.content) <= 800
    assert len(result.memory_ids) == 1
    assert len(result.content) < len("python " * 200)


def test_memory_prompt_context_rejects_invalid_budgets(tmp_path):
    store = MemoryStore(tmp_path / "budget-validation.sqlite3")
    with pytest.raises(ValueError):
        build_memory_prompt_context("query", store, limit=0)
    with pytest.raises(ValueError):
        build_memory_prompt_context("query", store, max_characters=100)
