import pytest

from senti.config import SentiSettings
from senti.contracts import ModelResponse, ToolCall
from senti.runtime import SentiHost
from senti.store import UnifiedDataStore
from senti.tools.registry import CapabilityRegistry
from senti.tools.task_tools import TaskBook, register_task_tools


def test_taskbook_lifecycle_and_validation(tmp_path):
    book = TaskBook(UnifiedDataStore(tmp_path / "s.sqlite3"))
    task = book.create("Fix the Wi-Fi drops", note="started", due_at="2026-11-20T18:00:00+05:30")
    assert task["status"] == "open" and task["notes"][0]["note"] == "started"
    updated = book.update(task["task_id"], status="in_progress", note="driver checked")
    assert updated["status"] == "in_progress" and len(updated["notes"]) == 2
    assert book.context()[0]["last_note"] == "driver checked"
    book.update(task["task_id"], status="done")
    assert book.list() == [] and len(book.list(include_done=True)) == 1
    with pytest.raises(ValueError):
        book.update(task["task_id"], status="whenever")
    with pytest.raises(ValueError):
        book.create("x")
    with pytest.raises(ValueError):
        book.create("valid title", due_at="tomorrow-ish")


def test_task_tools_are_simulated_and_approval_gated(tmp_path):
    store = UnifiedDataStore(tmp_path / "s.sqlite3")
    registry = CapabilityRegistry()
    register_task_tools(registry, store)
    preview = registry.simulate("senti_track_task", {"title": "Clean up disk space"})
    assert preview["intended_state"]["title"] == "Clean up disk space" and preview["simulation"] == "provider"
    assert registry.dispatch("senti_track_task", {"title": "Clean up disk space"}).status == "approval_required"
    result = registry.dispatch("senti_track_task", {"title": "Clean up disk space"}, approval=lambda *a: True)
    assert result.status == "succeeded"
    assert registry.dispatch("senti_list_tasks", {}).data["tasks"][0]["title"] == "Clean up disk space"


class Scripted:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def list_models(self, timeout=3.0):
        return ["SENTI"]

    def chat(self, request, *, model):
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else ModelResponse(
            model=model, content="Noted, sir.", elapsed_seconds=0.01)


def test_open_tasks_reach_the_model_once_and_emit_events(tmp_path):
    events = []
    call = ModelResponse(model="SENTI", content="", elapsed_seconds=0.01,
                         tool_calls=[ToolCall(name="senti_track_task", arguments={"title": "Fix Wi-Fi drops"})])
    fake = Scripted(call)
    host = SentiHost(settings=SentiSettings(), ollama=fake, store=UnifiedDataStore(tmp_path / "s.sqlite3"),
                     registry=CapabilityRegistry(), approval_handler=lambda *a: True, event_sink=events.append)
    register_task_tools(host.registry, host.store)
    conversation = host.new_conversation()
    host.chat("track fixing my wifi drops", conversation_id=conversation)
    assert any(e["type"] == "task" and e["action"] == "created" for e in events)
    host.chat("what's next?", conversation_id=conversation)
    assert "OPEN TASKS" in fake.requests[-1].messages[-1].content
    host.chat("and now?", conversation_id=conversation)
    assert "OPEN TASKS" not in fake.requests[-1].messages[-1].content  # unchanged -> not repeated
    assert host.list_tasks()[0]["title"] == "Fix Wi-Fi drops"
