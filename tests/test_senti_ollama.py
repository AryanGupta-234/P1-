import json
from unittest.mock import patch

from senti.contracts import ChatMessage, ModelRequest
from senti.ollama import OllamaClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _size):
        return json.dumps(self.payload).encode()


def test_chat_sends_think_false_and_parses_tool_calls():
    responses = [
        {"models": [{"name": "SENTI:latest"}]},
        {"model": "SENTI:latest", "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "senti_list_processes", "arguments": {"limit": 10}}}
        ]}, "prompt_eval_count": 10, "eval_count": 2},
    ]
    captured = []

    def fake_urlopen(request, timeout):
        if request.data:
            captured.append(json.loads(request.data.decode()))
            return FakeResponse(responses.pop(0))
        return FakeResponse(responses.pop(0))

    client = OllamaClient()
    with patch("senti.ollama.urlopen", side_effect=fake_urlopen):
        response = client.chat(
            ModelRequest(messages=[ChatMessage(role="user", content="show processes")]),
            model="SENTI",
        )
    assert captured[0]["model"] == "SENTI:latest"
    assert captured[0]["think"] is False
    assert response.tool_calls[0].name == "senti_list_processes"
    assert response.tool_calls[0].arguments == {"limit": 10}


def test_tool_result_message_uses_ollama_tool_role_without_extra_metadata():
    responses = [
        {"models": [{"name": "SENTI"}]},
        {"model": "SENTI", "message": {"role": "assistant", "content": "done"}, "eval_count": 1},
    ]
    captured = []

    def fake_urlopen(request, timeout):
        if request.data:
            captured.append(json.loads(request.data.decode()))
            return FakeResponse(responses.pop(0))
        return FakeResponse(responses.pop(0))

    client = OllamaClient()
    messages = [
        ChatMessage(role="user", content="run a check"),
        ChatMessage(role="tool", tool_name="senti_probe", content='{"status":"succeeded"}'),
    ]
    with patch("senti.ollama.urlopen", side_effect=fake_urlopen):
        client.chat(ModelRequest(messages=messages), model="SENTI")
    serialized_tool = captured[0]["messages"][-1]
    assert serialized_tool["role"] == "tool"
    assert "tool_name" not in serialized_tool


def test_default_latest_tag_resolution_is_exact_only():
    assert OllamaClient.resolve_installed_tag("SENTI", {"SENTI:latest"}) == "SENTI:latest"
    assert OllamaClient.resolve_installed_tag("SENTI", {"SENTI:v2"}) is None


def test_client_rejects_non_loopback_endpoint():
    try:
        OllamaClient("http://192.168.1.10:11434")
    except ValueError:
        pass
    else:
        raise AssertionError("non-loopback endpoint should be rejected")
