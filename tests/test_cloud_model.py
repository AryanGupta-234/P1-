import json
from io import BytesIO

import pytest

from aie.models.base import ChatMessage, ModelRequest
from aie.models.openai_compatible import (
    CloudEgressDenied,
    CloudModelUnavailable,
    OpenAICompatibleClient,
)


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def test_cloud_provider_requires_explicit_egress():
    with pytest.raises(CloudEgressDenied):
        OpenAICompatibleClient(
            base_url="https://api.example.com/v1",
            api_key="test-key",
            model="test-model",
        )


def test_cloud_provider_requires_https_and_environment_configuration():
    with pytest.raises(CloudModelUnavailable, match="HTTPS"):
        OpenAICompatibleClient(
            allow_cloud_egress=True,
            base_url="http://api.example.com/v1",
            api_key="test-key",
            model="test-model",
        )

    with pytest.raises(CloudModelUnavailable, match="AIE_CLOUD_API_KEY"):
        OpenAICompatibleClient(
            allow_cloud_egress=True,
            base_url="https://api.example.com/v1",
            api_key="",
            model="test-model",
        )


def test_cloud_chat_sends_only_explicit_prompt_and_returns_usage(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.headers, json.loads(request.data)))
        return FakeResponse(json.dumps({
            "model": "example-model-v1",
            "choices": [{"message": {"content": "Remote response"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }).encode())

    monkeypatch.setattr("aie.models.openai_compatible.urlopen", fake_urlopen)
    client = OpenAICompatibleClient(
        allow_cloud_egress=True,
        base_url="https://api.example.com/v1",
        api_key="not-a-real-key",
        model="example-model",
    )
    response = client.chat(ModelRequest(
        task="routine",
        messages=[ChatMessage(role="user", content="Explain this question.")],
        max_output_tokens=64,
    ))

    assert response.content == "Remote response"
    assert response.local_inference is False
    assert response.provider == "openai-compatible"
    assert response.prompt_tokens == 12
    assert response.completion_tokens == 5
    assert calls[0][0] == "https://api.example.com/v1/chat/completions"
    assert calls[0][2]["messages"] == [
        {"role": "user", "content": "Explain this question."}
    ]
    assert "response_format" not in calls[0][2]


def test_cloud_api_key_is_never_required_in_url():
    with pytest.raises(CloudModelUnavailable, match="Credentials must not be embedded"):
        OpenAICompatibleClient(
            allow_cloud_egress=True,
            base_url="https://user:secret@api.example.com/v1",
            api_key="test-key",
            model="test-model",
        )



def test_cloud_json_mode_requests_json_object(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return FakeResponse(json.dumps({
            "model": "example-model",
            "choices": [{"message": {"content": '{"ok":true}'}}],
        }).encode())

    monkeypatch.setattr("aie.models.openai_compatible.urlopen", fake_urlopen)
    client = OpenAICompatibleClient(
        allow_cloud_egress=True,
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="example-model",
    )
    response = client.chat(ModelRequest(
        response_format="json",
        messages=[ChatMessage(role="user", content="Return JSON.")],
    ))

    assert response.content == '{"ok":true}'
    assert captured["response_format"] == {"type": "json_object"}
