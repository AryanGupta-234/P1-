import pytest

from senti.semantic import Embedder, lexical_score
from senti.tools.router import rank_tool_schemas, select_tool_schemas, tool_document


def _schema(name, description, properties=None):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}}}}


SCHEMAS = [
    _schema("senti_list_network_configurations", "Inspect adapter IP, gateway, DNS and DHCP configuration."),
    _schema("senti_set_dns_servers", "Set DNS servers for one network adapter."),
    _schema("senti_list_processes", "List live processes with CPU and memory usage."),
    _schema("senti_set_master_volume", "Set Windows master output volume."),
    _schema("senti_open_settings", "Open a Windows Settings page.", {"page": {"enum": ["bluetooth", "display"]}}),
]


def test_lexical_fallback_uses_only_tool_text_and_tolerates_typos():
    names = [s["function"]["name"] for s in select_tool_schemas("change my DNS servers", SCHEMAS)]
    assert names[0] == "senti_set_dns_servers"
    assert lexical_score("blutooth", tool_document(SCHEMAS[4])) > 0.5


def test_unrelated_chat_gets_no_tools_in_retrieval_mode():
    assert select_tool_schemas("tell me a joke about penguins", SCHEMAS) == []


class FakeVectors:
    """Deterministic toy embedder: one axis per concept word."""
    AXES = ["memory", "process", "dns", "volume", "settings"]

    def __call__(self, texts):
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if axis in low else 0.0 for axis in self.AXES]
            if "ram" in low.split():
                vec[0] = vec[1] = 1.0
            out.append(vec if any(vec) else [0.01] * len(self.AXES))
        return out


def test_semantic_ranking_is_used_when_embeddings_are_available():
    selection = rank_tool_schemas("what is eating my ram", SCHEMAS, embedder=Embedder(FakeVectors()))
    assert selection.method == "semantic"
    assert selection.schemas[0]["function"]["name"] == "senti_list_processes"


def test_embedder_failure_degrades_to_lexical():
    def broken(_texts):
        raise RuntimeError("no embedding model")
    selection = rank_tool_schemas("set dns servers", SCHEMAS, embedder=Embedder(broken))
    assert selection.method == "lexical"
    assert selection.schemas[0]["function"]["name"] == "senti_set_dns_servers"


def test_pinned_tools_are_always_included():
    selection = rank_tool_schemas("joke", SCHEMAS, always_include=["senti_open_settings"])
    assert [s["function"]["name"] for s in selection.schemas] == ["senti_open_settings"]


def test_router_is_bounded_and_validates_inputs():
    with pytest.raises(ValueError):
        select_tool_schemas("x" * 12_001, SCHEMAS)
    with pytest.raises(ValueError):
        select_tool_schemas("dns", SCHEMAS, limit=0)
