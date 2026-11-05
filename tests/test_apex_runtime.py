from apex.config import ApexSettings
from apex.contracts import ModelResponse, ToolCall
from apex.runtime import ApexHost
from apex.store import UnifiedDataStore
from apex.tools.registry import CapabilityRegistry, ToolDefinition

class FakeOllama:
    def __init__(self): self.calls = 0
    def list_models(self, timeout=3.0): return ["APEX"]
    def chat(self, request, *, model):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(model=model, content="", elapsed_seconds=0.01,
                                 tool_calls=[ToolCall(name="apex_read_probe", arguments={})])
        return ModelResponse(model=model, content="Probe complete, sir.", elapsed_seconds=0.01)

def test_host_runs_bounded_host_dispatched_tool_loop(tmp_path):
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("apex_read_probe", "test read-only probe", {"type": "object"},
        "read_only", lambda _args: {"summary": "probe observed", "verified": True, "value": 7}))
    store = UnifiedDataStore(tmp_path / "apex.sqlite3")
    host = ApexHost(settings=ApexSettings(persist_conversations=True), ollama=FakeOllama(), store=store, registry=registry)
    result = host.chat("run the probe")
    assert result["response"] == "Probe complete, sir."
    assert result["tool_events"][0]["status"] == "succeeded"
    assert store.recent_messages(result["conversation_id"])[-1]["role"] == "assistant"

def test_runtime_manifest_does_not_depend_on_aie(tmp_path):
    host = ApexHost(settings=ApexSettings(), ollama=FakeOllama(),
                    store=UnifiedDataStore(tmp_path / "apex.sqlite3"), registry=CapabilityRegistry())
    manifest = host.runtime_manifest()
    assert manifest["product"] == "APEX"
    assert manifest["think"] is False
    assert "AIE" not in str(manifest["database_status"])

def test_conversation_persistence_is_opt_in(tmp_path):
    registry = CapabilityRegistry()
    store = UnifiedDataStore(tmp_path / "apex.sqlite3")
    host = ApexHost(settings=ApexSettings(), ollama=FakeOllama(), store=store, registry=registry)
    result = host.chat("hello")
    assert result["response"] == "Probe complete, sir."
    assert store.recent_messages(result["conversation_id"]) == []


def test_self_awareness_identity_is_answered_from_host_not_model(tmp_path):
    fake = FakeOllama()
    host = ApexHost(settings=ApexSettings(operator_name=None), ollama=fake,
                    store=UnifiedDataStore(tmp_path / "apex.sqlite3"), registry=CapabilityRegistry())
    result = host.chat("Who are you?")
    assert result["deterministic"] is True
    assert "APEX" in result["response"]
    assert fake.calls == 0


def test_self_awareness_creator_does_not_invent_attribution(tmp_path):
    fake = FakeOllama()
    host = ApexHost(settings=ApexSettings(operator_name=None), ollama=fake,
                    store=UnifiedDataStore(tmp_path / "apex.sqlite3"), registry=CapabilityRegistry())
    result = host.chat("Who made you?")
    assert "won't invent one" in result["response"]
    assert fake.calls == 0


def test_process_visibility_question_calls_registered_read_only_provider(tmp_path):
    fake = FakeOllama()
    registry = CapabilityRegistry()
    registry.register(ToolDefinition(
        "apex_list_processes", "List processes", {"type": "object"}, "read_only",
        lambda _args: {"summary": "observed process list", "count": 2,
                       "observed_at": "2026-11-05T10:00:00+05:30",
                       "processes": [{"pid": 101, "name": "explorer.exe"},
                                     {"pid": 202, "name": "notepad.exe"}]},
    ))
    host = ApexHost(settings=ApexSettings(), ollama=fake,
                    store=UnifiedDataStore(tmp_path / "apex.sqlite3"), registry=registry)
    result = host.chat("Can you see my running processes?")
    assert result["deterministic"] is True
    assert result["tool_events"][0]["status"] == "succeeded"
    assert "observed 2 processes" in result["response"]
    assert fake.calls == 0
