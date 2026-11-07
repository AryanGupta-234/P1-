"""Small, deterministic lexical router for task-relevant APEX tool schemas.

This is retrieval, not an intent classifier: it narrows the schema context by evidence
in names, descriptions and typed parameter options. It never authorizes an operation.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

_STOP_WORDS = {
    "a", "an", "and", "are", "can", "could", "do", "does", "for", "from",
    "give", "help", "i", "in", "is", "it", "me", "my", "of", "please",
    "show", "tell", "that", "the", "this", "to", "what", "when", "where",
    "which", "who", "with", "would", "you", "your",
}

_SYNONYMS = {
    "wifi": {"wireless", "network", "adapter"},
    "wireless": {"wifi", "network", "adapter"},
    "internet": {"network", "connectivity", "dns"},
    "connectivity": {"network", "internet", "dns"},
    "running": {"process", "processes"},
    "active": {"process", "processes", "window"},
    "cpu": {"processor", "performance", "process"},
    "ram": {"memory", "process"},
    "memory": {"ram", "process"},
    "disk": {"storage", "volume"},
    "space": {"storage", "volume"},
    "sound": {"audio", "volume"},
    "volume": {"audio", "sound"},
    "brightness": {"display", "screen"},
    "screen": {"display", "brightness", "window"},
    "app": {"application", "launch"},
    "apps": {"application", "applications", "launch"},
    "program": {"application", "launch"},
    "programs": {"application", "launch"},
    "bluetooth": {"settings", "device"},
    "scheduler": {"scheduled", "task"},
    "service": {"services"},
    "update": {"updates", "hotfix", "windows"},
    "pc": {"system", "hardware", "computer"},
    "computer": {"system", "hardware", "pc"},
    "laptop": {"system", "hardware", "device"},
    "machine": {"system", "hardware", "device"},
    "spec": {"specs", "hardware", "system"},
    "specs": {"spec", "hardware", "system"},
}


def _tokens(value: str) -> set[str]:
    normalized = value.casefold().replace("wi-fi", "wifi").replace("wi fi", "wifi")
    raw = set(re.findall(r"[a-z0-9]+", normalized))
    result = {item for item in raw if len(item) > 1 and item not in _STOP_WORDS}
    for token in tuple(result):
        if token.endswith("ies") and len(token) > 5:
            result.add(token[:-3] + "y")
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
            result.add(token[:-1])
    return result


def _expand(query_tokens: set[str]) -> set[str]:
    expanded = set(query_tokens)
    for token in query_tokens:
        expanded.update(_SYNONYMS.get(token, ()))
    return expanded


def select_tool_schemas(
    query: str,
    schemas: Iterable[dict],
    *,
    limit: int = 18,
) -> list[dict]:
    """Return a stable, bounded set of task-relevant tool schemas.

    Exact name matches carry the most weight, followed by descriptions and parameter
    schemas/enums. When no useful match is found, no tools are sent to the model.
    """
    if not isinstance(query, str) or len(query) > 12_000:
        raise ValueError("query must be a string of at most 12000 characters")
    if isinstance(limit, bool) or not 1 <= limit <= 40:
        raise ValueError("tool schema limit must be between 1 and 40")

    query_tokens = _expand(_tokens(query))
    if not query_tokens:
        return []

    ranked: list[tuple[int, int, dict]] = []
    for position, schema in enumerate(schemas):
        function = schema.get("function", {}) if isinstance(schema, dict) else {}
        name = function.get("name", "") if isinstance(function, dict) else ""
        description = function.get("description", "") if isinstance(function, dict) else ""
        parameters = function.get("parameters", {}) if isinstance(function, dict) else {}
        name_tokens = _tokens(str(name).replace("_", " "))
        description_tokens = _tokens(str(description))
        parameter_tokens = _tokens(json.dumps(parameters, ensure_ascii=False, sort_keys=True))
        score = (
            6 * len(query_tokens & name_tokens)
            + 3 * len(query_tokens & description_tokens)
            + len(query_tokens & parameter_tokens)
        )
        if score:
            ranked.append((score, -position, schema))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [schema for _score, _position, schema in ranked[:limit]]
