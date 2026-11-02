from __future__ import annotations

import pytest

from aie.prixon.identity import PRIXON_SYSTEM_PROMPT, apply_prixon_identity


def test_identity_is_prepended_without_discarding_caller_context() -> None:
    original = [
        {"role": "system", "content": "Use concise explanations."},
        {"role": "user", "content": "Who are you?"},
        {"role": "assistant", "content": "Prior turn."},
        {"role": "user", "content": "Continue."},
    ]
    result = apply_prixon_identity(original)
    assert result[0] == {"role": "system", "content": PRIXON_SYSTEM_PROMPT}
    assert result[1:] == original
    assert len(result) == len(original) + 1


def test_identity_explains_qwen_lineage_and_contextual_language() -> None:
    assert "Do not claim to be Qwen" in PRIXON_SYSTEM_PROMPT
    assert "profanity" in PRIXON_SYSTEM_PROMPT
    assert "blanket" in PRIXON_SYSTEM_PROMPT
    assert "must not bypass" in PRIXON_SYSTEM_PROMPT


def test_identity_rejects_unknown_roles() -> None:
    with pytest.raises(ValueError, match="unsupported role"):
        apply_prixon_identity([{"role": "tool", "content": "result"}])


def test_identity_rejects_empty_messages() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        apply_prixon_identity([{"role": "user", "content": " "}])
