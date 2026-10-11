import json
from io import BytesIO

import pytest

from aie.models.base import ChatMessage, ModelRequest, ModelResponse
from aie.models.ollama import (
    OllamaClient,
    OllamaRemoteEndpointDenied,
    OllamaUnavailable,
)
from aie.models.router import LocalModelRouter, ModelRoutingError


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def test_remote_ollama_requires_explicit_permission():
    with pytest.raises(OllamaRemoteEndpointDenied):
        OllamaClient(base_url="https://ollama.example.com")

    with pytest.raises(OllamaRemoteEndpointDenied):
        OllamaClient(base_url="http://192.168.1.20:11434", allow_remote=True)

    client = OllamaClient(base_url="https://ollama.example.com", allow_remote=True)
    assert client.base_url == "https://ollama.example.com"


def test_local_chat_uses_only_installed_model(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout, request.data))
        if request.full_url.endswith("/api/tags"):
            return FakeResponse(json.dumps({
                "models": [{"name": "qwen2.5:3b-instruct"}]
            }).encode())
        if request.full_url.endswith("/api/chat"):
            return FakeResponse(json.dumps({
                "model": "qwen2.5:3b-instruct",
                "message": {"content": "Local response"},
                "prompt_eval_count": 11,
                "eval_count": 7,
            }).encode())
        raise AssertionError(request.full_url)

    monkeypatch.setattr("aie.models.ollama.urlopen", fake_urlopen)
    client = OllamaClient()
    request = ModelRequest(
        task="routine",
        messages=[ChatMessage(role="user", content="Explain the event pipeline.")],
        max_output_tokens=128,
    )

    response = client.chat(request, model="qwen2.5:3b-instruct")

    assert response.content == "Local response"
    assert response.local_inference is True
    assert response.prompt_tokens == 11
    assert response.completion_tokens == 7
    assert [call[0].split("/")[-1] for call in calls] == ["tags", "chat"]
    sent = json.loads(calls[1][2].decode())
    assert sent["stream"] is False
    assert sent["model"] == "qwen2.5:3b-instruct"
    assert sent["options"]["num_predict"] == 128


def test_chat_refuses_uninstalled_model_without_posting(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(b'{"models": []}')

    monkeypatch.setattr("aie.models.ollama.urlopen", fake_urlopen)
    client = OllamaClient()
    request = ModelRequest(messages=[ChatMessage(role="user", content="hello")])

    with pytest.raises(OllamaUnavailable, match="not installed"):
        client.chat(request, model="missing:latest")

    assert calls == ["http://127.0.0.1:11434/api/tags"]


def test_router_uses_memory_aware_local_model(monkeypatch):
    class FakeProvider:
        def list_models(self):
            return ["qwen2.5:3b-instruct", "qwen2.5:7b-instruct"]

        def chat(self, request, *, model, installed_models=None):
            assert installed_models == self.list_models()
            return ModelResponse(
                model=model,
                content="ok",
                elapsed_seconds=0.1,
                local_inference=True,
                provider="fake",
            )

    monkeypatch.setattr(
        "aie.models.router.runtime_profile",
        lambda: {"memory_available_gib": 3.0},
    )
    response = LocalModelRouter(FakeProvider()).generate(
        ModelRequest(task="complex", messages=[ChatMessage(role="user", content="test")])
    )

    assert response.model == "qwen2.5:3b-instruct"


def test_router_reports_when_no_eligible_model_is_installed(monkeypatch):
    class EmptyProvider:
        def list_models(self):
            return []

        def chat(self, request, *, model, installed_models=None):
            raise AssertionError("chat must not be called")

    monkeypatch.setattr(
        "aie.models.router.runtime_profile",
        lambda: {"memory_available_gib": 12.0},
    )
    with pytest.raises(ModelRoutingError, match="No installed reasoning model"):
        LocalModelRouter(EmptyProvider()).generate(
            ModelRequest(messages=[ChatMessage(role="user", content="test")])
        )


def test_local_ollama_embeddings_use_api_embed_and_validate_vectors(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, json.loads(request.data) if request.data else None))
        if request.full_url.endswith("/api/tags"):
            return FakeResponse(json.dumps({
                "models": [{"name": "nomic-embed-text:latest"}]
            }).encode())
        if request.full_url.endswith("/api/embed"):
            return FakeResponse(json.dumps({
                "model": "nomic-embed-text:latest",
                "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            }).encode())
        raise AssertionError(request.full_url)

    monkeypatch.setattr("aie.models.ollama.urlopen", fake_urlopen)
    client = OllamaClient()
    vectors = client.embed(
        ["first memory", "second memory"],
        model="nomic-embed-text:latest",
    )

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert calls[1][0] == "http://127.0.0.1:11434/api/embed"
    assert calls[1][1]["truncate"] is False
    assert calls[1][1]["input"] == ["first memory", "second memory"]


def test_local_ollama_embeddings_refuse_missing_model_without_pull(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(b'{"models": []}')

    monkeypatch.setattr("aie.models.ollama.urlopen", fake_urlopen)
    with pytest.raises(OllamaUnavailable, match="never downloads"):
        OllamaClient().embed(["query"], model="missing-embed-model")

    assert calls == ["http://127.0.0.1:11434/api/tags"]


def test_local_ollama_embeddings_reject_non_finite_vectors(monkeypatch):
    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/tags"):
            return FakeResponse(b'{"models":[{"name":"embed:latest"}]}')
        return FakeResponse(b'{"embeddings":[[NaN, 0.0]]}')

    monkeypatch.setattr("aie.models.ollama.urlopen", fake_urlopen)
    with pytest.raises(OllamaUnavailable, match="non-finite"):
        OllamaClient().embed(["query"], model="embed:latest")
