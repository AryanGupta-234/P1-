import json
import threading

import pytest

from aie.ollama import (
    OllamaCancelled,
    OllamaClient,
    OllamaError,
    _NoRedirectHandler,
)


class Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.raw[:limit]


def fake_opener(payload, seen=None, after_read=None):
    def open_request(request, timeout):
        if seen is not None:
            seen.append((request, timeout))
        if after_read is not None:
            after_read()
        return Response(payload)
    return open_request


def test_chat_posts_non_streaming_messages_to_loopback():
    seen = []
    client = OllamaClient(opener=fake_opener(
        {"model": "qwen2.5:3b-instruct", "message": {"content": "hello"},
         "done": True, "prompt_eval_count": 4, "eval_count": 2},
        seen,
    ))
    result = client.chat(
        "qwen2.5:3b-instruct",
        [{"role": "user", "content": "hi"}],
        format="json",
    )
    request, timeout = seen[0]
    body = json.loads(request.data)
    assert request.full_url == "http://127.0.0.1:11434/api/chat"
    assert body["stream"] is False
    assert body["format"] == "json"
    assert result.content == "hello"
    assert result.done
    assert result.prompt_tokens == 4
    assert result.output_tokens == 2
    assert timeout == 60.0


def test_chat_rejects_tool_roles_and_malformed_messages():
    client = OllamaClient(opener=fake_opener({}))
    with pytest.raises(ValueError):
        client.chat("model", [{"role": "tool", "content": "run"}])
    with pytest.raises(ValueError):
        client.chat("model", [{"role": "user", "content": 123}])


def test_chat_rejects_invalid_response_shape():
    client = OllamaClient(opener=fake_opener({"done": True}))
    with pytest.raises(OllamaError, match="message.content"):
        client.chat("model", [{"role": "user", "content": "hi"}])


def test_embeddings_validate_count_finiteness_and_dimensions():
    client = OllamaClient(opener=fake_opener({
        "model": "nomic-embed-text:latest",
        "embeddings": [[0.1, 0.2], [0.3, 0.4]],
    }))
    result = client.embed(
        "nomic-embed-text:latest", ["first", "second"], expected_dimensions=2
    )
    assert result.dimensions == 2
    assert len(result.embeddings) == 2

    mismatch_client = OllamaClient(opener=fake_opener({"model": "model", "embeddings": [[0.1, 0.2]]}))
    with pytest.raises(OllamaError, match="dimension mismatch"):
        mismatch_client.embed("model", "text", expected_dimensions=3)


@pytest.mark.parametrize("vectors", [
    [],
    [[]],
    [[0.1], [0.2, 0.3]],
    [[float("nan")]],
    [[True]],
])
def test_embeddings_reject_invalid_vectors(vectors):
    client = OllamaClient(opener=fake_opener({"embeddings": vectors}))
    with pytest.raises(OllamaError):
        client.embed("model", ["one", "two"] if len(vectors) == 2 else "one")


def test_cancelled_request_is_not_sent():
    seen = []
    client = OllamaClient(opener=fake_opener({}, seen))
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(OllamaCancelled):
        client.chat("model", [{"role": "user", "content": "hi"}],
                    cancel_event=cancelled)
    assert seen == []


def test_cancellation_during_request_discards_response():
    cancelled = threading.Event()
    client = OllamaClient(opener=fake_opener(
        {"message": {"content": "should not escape"}},
        after_read=cancelled.set,
    ))
    with pytest.raises(OllamaCancelled):
        client.chat("model", [{"role": "user", "content": "hi"}],
                    cancel_event=cancelled)


@pytest.mark.parametrize("url", [
    "http://192.168.1.5:11434",
    "https://example.com",
    "http://user:pass@127.0.0.1:11434",
    "http://127.0.0.1:11434?redirect=1",
    "http://127.0.0.1:99999",
    "http://127.0.0.1:11434/custom-path",
])
def test_client_rejects_non_loopback_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        OllamaClient(base_url=url)


@pytest.mark.parametrize("timeout", [0, -1, 601, True, float("inf"), float("nan")])
def test_client_rejects_invalid_timeouts(timeout):
    with pytest.raises(ValueError):
        OllamaClient(timeout=timeout)


@pytest.mark.parametrize("inputs", [[], 42, ["valid", ""]])
def test_embeddings_reject_invalid_input_values(inputs):
    client = OllamaClient(opener=fake_opener({}))
    with pytest.raises(ValueError):
        client.embed("model", inputs)


def test_embeddings_reject_boolean_dimension():
    client = OllamaClient(opener=fake_opener({}))
    with pytest.raises(ValueError):
        client.embed("model", "text", expected_dimensions=True)


def test_redirects_are_never_followed():
    handler = _NoRedirectHandler()
    request = __import__("urllib.request", fromlist=["Request"]).Request(
        "http://127.0.0.1:11434/api/chat"
    )
    assert handler.redirect_request(
        request, None, 302, "Found", {}, "http://example.com/collect"
    ) is None


def test_oversized_response_is_rejected():
    class LargeResponse(Response):
        def read(self, limit):
            return b"x" * limit

    client = OllamaClient(opener=lambda request, timeout: LargeResponse({}))
    with pytest.raises(OllamaError, match="4 MiB"):
        client.chat("model", [{"role": "user", "content": "hi"}])


def test_chat_rejects_non_boolean_completion_metadata():
    client = OllamaClient(opener=fake_opener({
        "message": {"content": "hello"},
        "done": "false",
    }))
    with pytest.raises(OllamaError, match="boolean done"):
        client.chat("model", [{"role": "user", "content": "hi"}])


def test_request_payload_is_bounded_before_network_call():
    seen = []
    client = OllamaClient(opener=fake_opener({}, seen))
    with pytest.raises(ValueError, match="1 MiB"):
        client.chat("model", [{"role": "user", "content": "x" * (1024 * 1024)}])
    assert seen == []


def test_request_rejects_non_finite_option_values():
    seen = []
    client = OllamaClient(opener=fake_opener({}, seen))
    with pytest.raises(ValueError, match="finite JSON"):
        client.chat(
            "model",
            [{"role": "user", "content": "hi"}],
            options={"temperature": float("nan")},
        )
    assert seen == []
