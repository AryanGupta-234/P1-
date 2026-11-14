"""Identity, dynamic tool choice, simulation-before-approval, dynamic thinking and learning."""
from senti.config import SentiSettings
from senti.contracts import ModelResponse, ToolCall
from senti.runtime import SentiHost
from senti.store import UnifiedDataStore
from senti.tools.registry import CapabilityRegistry, ToolDefinition


class ScriptedOllama:
    """Replays a list of responses; records every request."""

    def __init__(self, *responses, system_prompt=None):
        self.responses = list(responses)
        self.requests = []
        self._system = system_prompt

    def list_models(self, timeout=3.0):
        return ["SENTI"]

    def chat(self, request, *, model):
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(model=model, content="Done, sir.", elapsed_seconds=0.01)

    def __getattr__(self, name):
        if name == "model_system_prompt" and self._system is not None:
            return lambda model: self._system
        raise AttributeError(name)


def _call(name, **arguments):
    return ModelResponse(model="SENTI", content="", elapsed_seconds=0.01,
                         tool_calls=[ToolCall(name=name, arguments=arguments)])


LEVEL_SCHEMA = {"type": "object", "properties": {"level": {"type": "integer"}},
                "required": ["level"], "additionalProperties": False}


def _level_registry(simulate=None):
    registry = CapabilityRegistry()
    registry.register(ToolDefinition(
        "senti_set_level", "Set a level", LEVEL_SCHEMA, "low",
        lambda args: {"summary": f"level set to {args['level']}", "verified": True},
        simulate=simulate))
    return registry


def _host(tmp_path, ollama, registry=None, **kwargs):
    return SentiHost(settings=SentiSettings(), ollama=ollama,
                     store=UnifiedDataStore(tmp_path / "senti.sqlite3"),
                     registry=registry or CapabilityRegistry(), **kwargs)


def test_identity_comes_from_private_modelfile_and_the_model_answers(tmp_path):
    fake = ScriptedOllama(system_prompt="PRIVATE-SENTI-FRAMEWORK")
    _host(tmp_path, fake).chat("Who are you?")
    system = fake.requests[0].messages[0].content
    assert system.startswith("PRIVATE-SENTI-FRAMEWORK")
    assert "OPERATING PROTOCOL" in system
    assert len(fake.requests) == 1  # no keyword shortcut: the model itself answered


def test_fallback_identity_never_claims_to_be_qwen(tmp_path):
    fake = ScriptedOllama()
    _host(tmp_path, fake).chat("hi")
    system = fake.requests[0].messages[0].content
    assert system.startswith("You are SENTI")
    assert "not Qwen" in system


def test_model_is_offered_every_available_tool_and_chooses_itself(tmp_path):
    fake = ScriptedOllama()
    _host(tmp_path, fake, _level_registry()).chat("any phrasing at all")
    offered = {t["function"]["name"] for t in fake.requests[0].tools}
    assert {"senti_set_level", "senti_find_tools", "senti_simulate_action",
            "senti_get_runtime_manifest", "senti_recall_experience"} <= offered


def test_mutation_is_simulated_before_approval_and_lifecycle_events_flow(tmp_path):
    seen, events = {}, []

    def approve(name, arguments, risk, preview):
        seen.update(preview)
        return True

    registry = _level_registry(simulate=lambda args: {
        "current_state": {"level": 70}, "intended_state": {"level": args["level"]},
        "effect": "Changes the level."})
    host = _host(tmp_path, ScriptedOllama(_call("senti_set_level", level=40)), registry,
                 approval_handler=approve, event_sink=events.append)
    result = host.chat("set the level to 40")
    assert result["tool_events"][0]["status"] == "succeeded"
    assert seen["current_state"] == {"level": 70} and seen["simulation"] == "provider"
    states = [e["state"] for e in events if e["type"] == "state"]
    assert states[0] == "listening" and "awaiting_authorization" in states and states[-1] == "completed"
    assert any(e["type"] == "tool" and e["phase"] == "simulated" for e in events)
    assert any(e["type"] == "memory" and e["action"] == "learned" for e in events)
    assert any(e["type"] == "reply" for e in events)


def test_invalid_simulation_blocks_execution_before_approval(tmp_path):
    asked = []
    registry = _level_registry()
    host = _host(tmp_path, ScriptedOllama(_call("senti_set_level", level="loud")), registry,
                 approval_handler=lambda *a: asked.append(a) or True)
    result = host.chat("make it loud")
    assert result["tool_events"][0]["status"] == "denied"
    assert asked == []


def test_simulate_tool_never_executes(tmp_path):
    ran = []
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_set_level", "Set a level", LEVEL_SCHEMA, "low",
                                     lambda args: ran.append(args) or {"summary": "ok"}))
    host = _host(tmp_path, ScriptedOllama(
        _call("senti_simulate_action", tool="senti_set_level", arguments={"level": 5})), registry)
    result = host.chat("what would happen if you set the level to 5?")
    assert result["tool_events"][0]["status"] == "succeeded"
    assert ran == []


def test_verified_outcome_is_learned_and_recalled_for_a_similar_goal(tmp_path):
    host = _host(tmp_path, ScriptedOllama(_call("senti_set_level", level=40)), _level_registry(),
                 approval_handler=lambda *a: True)
    host.chat("set the speaker level to 40")
    recalled = host.learner.recall("set speaker level to 30")
    assert recalled and recalled[0]["outcome"] == "worked"
    assert recalled[0]["steps"][0]["tool"] == "senti_set_level"
    # The next similar request receives the recalled experience in context.
    follow_up = ScriptedOllama()
    host.ollama = follow_up
    host.chat("set the speaker level to 25")
    assert "RECALLED EXPERIENCE" in follow_up.requests[0].messages[-1].content
    assert "RECALLED EXPERIENCE (" not in follow_up.requests[0].messages[0].content  # system block stays fixed


def test_thinking_turns_on_dynamically_after_a_failed_tool(tmp_path):
    def boom(_args):
        raise RuntimeError("provider exploded")

    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_broken", "always fails", {"type": "object"}, "read_only", boom))
    fake = ScriptedOllama(_call("senti_broken"))
    host = _host(tmp_path, fake, registry)
    host.chat("check the thing")
    assert fake.requests[0].think is False
    assert fake.requests[1].think is True
    recalled = host.learner.recall("check the thing")
    assert recalled and recalled[0]["outcome"] == "did_not_work"


def test_think_mode_off_never_thinks(tmp_path):
    def boom(_args):
        raise RuntimeError("x")

    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_broken", "always fails", {"type": "object"}, "read_only", boom))
    fake = ScriptedOllama(_call("senti_broken"))
    SentiHost(settings=SentiSettings(think_mode="off"), ollama=fake,
              store=UnifiedDataStore(tmp_path / "s.sqlite3"), registry=registry).chat("check")
    assert all(r.think is False for r in fake.requests)


def test_tool_budget_exhaustion_produces_an_honest_summary(tmp_path):
    registry = CapabilityRegistry()
    registry.register(ToolDefinition("senti_probe", "probe", {"type": "object"}, "read_only",
                                     lambda args: {"summary": "observed", "verified": True}))
    calls = [ModelResponse(model="SENTI", content="", elapsed_seconds=0.01,
                           tool_calls=[ToolCall(name="senti_probe", arguments={"n": i})]) for i in range(8)]
    fake = ScriptedOllama(*calls)
    host = SentiHost(settings=SentiSettings(max_tool_rounds=2), ollama=fake,
                     store=UnifiedDataStore(tmp_path / "s.sqlite3"), registry=registry)
    result = host.chat("investigate")
    assert result["tool_limit_reached"] is True
    final = fake.requests[-1]
    assert final.messages[-1].content.startswith("[SENTI host] Tool budget")
    assert final.tools == fake.requests[0].tools  # tool list stays fixed so the cache stays valid


def test_conversation_transcript_is_append_only_for_cache_reuse(tmp_path):
    fake = ScriptedOllama(_call("senti_set_level", level=10))
    host = _host(tmp_path, fake, _level_registry(), approval_handler=lambda *a: True)
    conversation = host.new_conversation()
    host.chat("set level to 10", conversation_id=conversation)
    host.chat("thanks", conversation_id=conversation)
    first, second, third = fake.requests
    # Every request starts with exactly the previous request's messages (an append-only prefix).
    assert [m.model_dump() for m in second.messages[:len(first.messages)]] == [m.model_dump() for m in first.messages]
    assert [m.model_dump() for m in third.messages[:len(second.messages)]] == [m.model_dump() for m in second.messages]
    assert first.tools == second.tools == third.tools


def test_prime_preloads_the_fixed_prefix(tmp_path):
    fake = ScriptedOllama(ModelResponse(model="SENTI", content="Ready.", elapsed_seconds=0.01))
    host = _host(tmp_path, fake)
    result = host.prime()
    assert result["status"] == "primed"
    host.chat("hello")
    assert fake.requests[1].messages[:3] == fake.requests[0].messages[:2] + [fake.requests[1].messages[2]]
    assert fake.requests[1].messages[2].content == "Ready."


def test_common_mutations_get_current_to_intended_previews(monkeypatch, tmp_path):
    from senti.tools import simulations
    from senti.windows import audio
    monkeypatch.setattr(audio, "get_master_volume", lambda: {"volume_percent": 72, "muted": False})
    registry = CapabilityRegistry()
    registry.register(ToolDefinition(
        "senti_set_master_volume", "Set volume",
        {"type": "object", "properties": {"volume_percent": {"type": "integer", "minimum": 0, "maximum": 100}},
         "required": ["volume_percent"], "additionalProperties": False},
        "low", lambda args: {"summary": "set"}))
    assert simulations.attach_simulations(registry) == 1
    preview = registry.simulate("senti_set_master_volume", {"volume_percent": 30})
    assert preview["simulation"] == "provider"
    assert preview["current_state"]["volume_percent"] == 72
    assert preview["intended_state"] == {"volume_percent": 30}
