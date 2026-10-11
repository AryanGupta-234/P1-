import pytest
from pydantic import ValidationError

from aie.models.base import ChatMessage, ModelRequest


def test_model_request_enforces_combined_input_character_budget():
    request = ModelRequest(
        response_format="json",
        max_input_characters=512,
        messages=[ChatMessage(role="user", content="x" * 512)],
    )
    assert request.max_input_characters == 512
    assert request.response_format == "json"

    with pytest.raises(ValidationError, match="combined message content exceeds"):
        ModelRequest(
            max_input_characters=512,
            messages=[
                ChatMessage(role="system", content="s" * 300),
                ChatMessage(role="user", content="u" * 300),
            ],
        )


def test_model_request_rejects_invalid_input_budget_bounds():
    with pytest.raises(ValidationError):
        ModelRequest(
            max_input_characters=128,
            messages=[ChatMessage(role="user", content="hello")],
        )
    with pytest.raises(ValidationError):
        ModelRequest(
            max_input_characters=120_001,
            messages=[ChatMessage(role="user", content="hello")],
        )


def test_model_request_rejects_unsupported_response_formats():
    with pytest.raises(ValidationError):
        ModelRequest(
            response_format="yaml",
            messages=[ChatMessage(role="user", content="hello")],
        )
