import json

import pytest

from aie.cognition import build_cognitive_messages


def test_cognitive_prompt_separates_observations_from_question():
    context = {"processes": [{"image": "notepad.exe"}], "coverage": {"processes": "partial"}}
    messages = build_cognitive_messages(context, "What is running?")
    assert [item["role"] for item in messages] == ["system", "user"]
    assert "untrusted data" in messages[0]["content"]
    assert json.dumps(context, separators=(",", ":")) in messages[1]["content"]
    assert "What is running?" in messages[1]["content"]


@pytest.mark.parametrize(
    "context,question,kwargs",
    [
        ([], "question", {}),
        ({}, "", {}),
        ({}, "x" * 4001, {}),
        ({"large": "x" * 100}, "question", {"max_context_bytes": 10}),
        ({"bad": float("nan")}, "question", {}),
    ],
)
def test_cognitive_prompt_rejects_invalid_or_unbounded_inputs(context, question, kwargs):
    with pytest.raises(ValueError):
        build_cognitive_messages(context, question, **kwargs)
