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
