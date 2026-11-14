from senti.config import SentiSettings
from senti.contracts import ModelResponse, ToolCall
from senti.runtime import SentiHost
from senti.store import UnifiedDataStore
from senti.tools.registry import CapabilityRegistry, ToolDefinition

class FakeOllama:
    def __init__(self):
        self.calls = 0
        self.requests = []
    def list_models(self, timeout=3.0): return ["SENTI"]
    def chat(self, request, *, model):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ModelResponse(model=model, content="", elapsed_seconds=0.01,
                                 tool_calls=[ToolCall(name="senti_read_probe", arguments={})])
        return ModelResponse(model=model, content="Probe complete, sir.", elapsed_seconds=0.01)

def test_host_runs_bounded_host_dispatched_tool_loop(tmp_path):
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_read_probe", "test read-only probe", {"type": "object"},
        "read_only", lambda _args: {"summary": "probe observed", "verified": True, "value": 7}))
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    host = SentiHost(settings=SentiSettings(persist_conversations=True), ollama=FakeOllama(), store=store, registry=registry)
    result = host.chat("run the probe")
    assert result["response"] == "Probe complete, sir."
    assert result["tool_events"][0]["status"] == "succeeded"
    assert store.recent_messages(result["conversation_id"])[-1]["role"] == "assistant"

def test_runtime_manifest_does_not_depend_on_aie(tmp_path):
    host = SentiHost(settings=SentiSettings(), ollama=FakeOllama(),
                    store=UnifiedDataStore(tmp_path / "senti.sqlite3"), registry=CapabilityRegistry())
    manifest = host.runtime_manifest()
    assert manifest["product"] == "SENTI"
    assert manifest["think_mode"] == "auto"
    assert manifest["policy"]["mutations_are_simulated_before_approval"] is True
    assert "AIE" not in str(manifest["database_status"])


def test_conversation_persistence_can_be_disabled(tmp_path):
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    host = SentiHost(settings=SentiSettings(persist_conversations=False), ollama=FakeOllama(),
                     store=store, registry=CapabilityRegistry())
    result = host.chat("hello")
    assert result["response"] == "Probe complete, sir."
    assert store.recent_messages(result["conversation_id"]) == []


def test_relevant_normal_memory_is_injected_as_untrusted_reference_data(tmp_path):
    fake = FakeOllama()
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    store.add_memory(
        namespace="technical",
        memory_type="project_context",
        payload={"note": "quasar stack uses the bounded local memory retriever"},
        source="explicit_user_request",
    )
    store.add_memory(
        namespace="technical",
        memory_type="fact",
        payload={"note": "quasar stack private memory must stay hidden"},
        source="explicit_user_request",
        sensitivity="sensitive",
    )
    host = SentiHost(
        settings=SentiSettings(),
        ollama=fake,
        store=store,
        registry=CapabilityRegistry(),
    )

    host.chat("Remind me about the quasar stack details")

    system_content = fake.requests[0].messages[-1].content
    assert "bounded local memory retriever" in system_content
    assert "quasar stack private memory" not in system_content
    assert "untrusted reference data" in system_content


def test_memory_context_is_not_added_for_unrelated_chat(tmp_path):
    fake = FakeOllama()
    store = UnifiedDataStore(tmp_path / "senti.sqlite3")
    store.add_memory(
        namespace="technical",
        memory_type="fact",
        payload={"note": "quasar stack details"},
        source="explicit_user_request",
    )
    host = SentiHost(settings=SentiSettings(), ollama=fake,
                    store=store, registry=CapabilityRegistry())

    host.chat("Tell me a joke about penguins")

    system_content = fake.requests[0].messages[-1].content
    assert "RELEVANT SENTI MEMORY" not in system_content
