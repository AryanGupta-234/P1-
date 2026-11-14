"""Meaning-based selection of task-relevant SENTI tool schemas.

A 4B local model reasons best over a short tool list, so the host retrieves the tools whose
meaning is closest to the request (local embeddings), falling back to a generic fuzzy
lexical score. There is no hand-written vocabulary: what a tool is "about" comes only from
its own name, description and parameter schema.

This is retrieval, never authorization. The model can also ask for more tools at run time
through ``senti_find_tools`` (see the runtime), so a missed retrieval is recoverable.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from senti.semantic import Embedder, rank


@dataclass(slots=True)
class ToolSelection:
    schemas: list[dict]
    method: str
    top_score: float
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def operational(self) -> bool:
        """True when the request clearly maps onto at least one capability."""
        threshold = SEMANTIC_ACTION_THRESHOLD if self.method == "semantic" else LEXICAL_ACTION_THRESHOLD
        return self.top_score >= threshold


# Calibrated on nomic-embed-text with tool documents; lexical scores are overlap ratios.
SEMANTIC_MIN_SCORE = 0.50
SEMANTIC_ACTION_THRESHOLD = 0.58
SEMANTIC_RELATIVE_FLOOR = 0.82
LEXICAL_MIN_SCORE = 0.30
LEXICAL_ACTION_THRESHOLD = 0.45


def tool_document(schema: dict) -> str:
    function = schema.get("function", {}) if isinstance(schema, dict) else {}
    if not isinstance(function, dict):
        return ""
    name = str(function.get("name", "")).removeprefix("senti_").replace("_", " ")
    description = str(function.get("description", ""))
    parameters = function.get("parameters", {})
    hints: list[str] = []
    if isinstance(parameters, dict):
        for key, prop in (parameters.get("properties") or {}).items():
            hints.append(str(key).replace("_", " "))
            if isinstance(prop, dict) and isinstance(prop.get("enum"), list):
                hints.extend(str(v).replace("_", " ").replace("-", " ") for v in prop["enum"][:40])
    return f"{name}. {description} Parameters: {', '.join(hints)}" if hints else f"{name}. {description}"


def schema_name(schema: dict) -> str:
    function = schema.get("function", {}) if isinstance(schema, dict) else {}
    return str(function.get("name", "")) if isinstance(function, dict) else ""


def rank_tool_schemas(query: str, schemas: Iterable[dict], *, limit: int = 12,
                      embedder: Embedder | None = None,
                      always_include: Iterable[str] = ()) -> ToolSelection:
    if not isinstance(query, str) or len(query) > 12_000:
        raise ValueError("query must be a string of at most 12000 characters")
    if isinstance(limit, bool) or not 1 <= limit <= 40:
        raise ValueError("tool schema limit must be between 1 and 40")
    schemas = [s for s in schemas if isinstance(s, dict)]
    pinned_names = set(always_include)
    candidates = [s for s in schemas if schema_name(s) not in pinned_names]
    pinned = [s for s in schemas if schema_name(s) in pinned_names]
    if not query.strip() or not candidates:
        return ToolSelection(schemas=pinned, method="none", top_score=0.0)

    scores, method = rank(query, (tool_document(s) for s in candidates), embedder=embedder)
    ordered = sorted(zip(scores, range(len(candidates)), candidates), key=lambda x: (-x[0], x[1]))
    top = ordered[0][0] if ordered else 0.0
    if method == "semantic":
        floor = max(SEMANTIC_MIN_SCORE, top * SEMANTIC_RELATIVE_FLOOR)
    else:
        floor = LEXICAL_MIN_SCORE
    chosen = [schema for score, _i, schema in ordered if score >= floor][:limit]
    return ToolSelection(
        schemas=chosen + pinned,
        method=method,
        top_score=round(top, 4),
        scores={schema_name(s): round(score, 4) for score, _i, s in ordered[:limit]},
    )


def select_tool_schemas(query: str, schemas: Iterable[dict], *, limit: int = 12,
                        embedder: Embedder | None = None) -> list[dict]:
    """Return a bounded list of relevant tool schemas (empty for unrelated chat)."""
    return rank_tool_schemas(query, schemas, limit=limit, embedder=embedder).schemas


def describe_tools(schemas: Iterable[dict]) -> list[dict]:
    """Compact name/description rows for discovery results (no full JSON schema)."""
    rows = []
    for schema in schemas:
        function = schema.get("function", {}) if isinstance(schema, dict) else {}
        if isinstance(function, dict):
            rows.append({"name": function.get("name"),
                         "description": str(function.get("description", ""))[:240],
                         "parameters": sorted((function.get("parameters") or {}).get("properties", {}))})
    return json.loads(json.dumps(rows, ensure_ascii=False))
