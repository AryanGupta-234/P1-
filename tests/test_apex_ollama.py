import json
from unittest.mock import patch

from apex.contracts import ChatMessage, ModelRequest
from apex.ollama import OllamaClient


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
        {"models": [{"name": "APEX:latest"}]},
        {"model": "APEX:latest", "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "apex_list_processes", "arguments": {"limit": 10}}}
        ]}, "prompt_eval_count": 10, "eval_count": 2},
    ]
    captured = []

    def fake_urlopen(request, timeout):
        if request.data:
            captured.append(json.loads(request.data.decode()))
            return FakeResponse(responses.pop(0))
        return FakeResponse(responses.pop(0))

    client = OllamaClient()
    with patch("apex.ollama.urlopen", side_effect=fake_urlopen):
        response = client.chat(
            ModelRequest(messages=[ChatMessage(role="user", content="show processes")]),
            model="APEX",
        )
    assert captured[0]["model"] == "APEX:latest"
    assert captured[0]["think"] is False
    assert response.tool_calls[0].name == "apex_list_processes"
    assert response.tool_calls[0].arguments == {"limit": 10}


def test_tool_result_message_uses_ollama_tool_role_without_extra_metadata():
    responses = [
        {"models": [{"name": "APEX"}]},
        {"model": "APEX", "message": {"role": "assistant", "content": "done"}, "eval_count": 1},
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
        ChatMessage(role="tool", tool_name="apex_probe", content='{"status":"succeeded"}'),
    ]
    with patch("apex.ollama.urlopen", side_effect=fake_urlopen):
        client.chat(ModelRequest(messages=messages), model="APEX")
    serialized_tool = captured[0]["messages"][-1]
    assert serialized_tool["role"] == "tool"
    assert "tool_name" not in serialized_tool


def test_default_latest_tag_resolution_is_exact_only():
    assert OllamaClient.resolve_installed_tag("APEX", {"APEX:latest"}) == "APEX:latest"
    assert OllamaClient.resolve_installed_tag("APEX", {"APEX:v2"}) is None


def test_client_rejects_non_loopback_endpoint():
    try:
        OllamaClient("http://192.168.1.10:11434")
    except ValueError:
        pass
    else:
        raise AssertionError("non-loopback endpoint should be rejected")
