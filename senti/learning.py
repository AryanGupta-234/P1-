"""Evidence-based learning: SENTI remembers what actually worked and what failed.

This is outcome memory, not training. Nothing here changes model weights.

After a request that used tools, the host records a compact procedure:
- ``procedure``: the goal plus the tool steps that succeeded (with ``verified`` when the
  provider confirmed the outcome);
- ``lesson``: an approach that failed or was unavailable, so SENTI avoids repeating it.

Procedures are recalled by meaning for later requests and offered to the model as
reference data. Argument values that could carry user content are redacted, and nothing
sensitive is stored.
"""
from __future__ import annotations

import json
from typing import Any

from senti.semantic import Embedder, rank

NAMESPACE = "procedures"
META_TOOLS = {"senti_get_runtime_manifest", "senti_find_tools", "senti_simulate_action",
              "senti_recall_experience", "senti_search_memory"}
_CONTENT_KEYS = {"text", "value", "payload", "content", "body", "clipboard"}
_LEARNABLE = {"succeeded", "failed", "unavailable"}


def _redact(arguments: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in list(arguments.items())[:12]:
        if key.casefold() in _CONTENT_KEYS:
            clean[key] = "<redacted>"
        elif isinstance(value, str):
            clean[key] = value[:120]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = [v if isinstance(v, (int, float, bool)) else str(v)[:60] for v in value[:8]]
        else:
            clean[key] = "<object>"
    return clean


class ExperienceLearner:
    def __init__(self, store, embedder: Embedder | None = None):
        self.store = store
        self.embedder = embedder

    def _rows(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self.store.search_memories("", namespace=NAMESPACE, limit=limit, include_sensitive=False)
        except Exception:
            return []

    def learn(self, goal: str, trace: list[dict[str, Any]]) -> str | None:
        """Record the outcome of one request. Returns a short summary, or None if nothing learned."""
        steps = [step for step in trace
                 if step.get("tool") not in META_TOOLS and step.get("status") in _LEARNABLE]
        if not steps or not isinstance(goal, str) or not goal.strip():
            return None
        succeeded = [s for s in steps if s["status"] == "succeeded"]
        failed = [s for s in steps if s["status"] != "succeeded"]
        kind = "procedure" if succeeded and not failed else ("lesson" if not succeeded else "procedure")
        payload = {
            "goal": goal.strip()[:400],
            "steps": [{"tool": s["tool"], "arguments": _redact(s.get("arguments") or {}),
                       "status": s["status"], "verified": bool(s.get("verified"))} for s in steps[:8]],
            "outcome": "worked" if kind == "procedure" else "did_not_work",
            "notes": [str(s.get("summary", ""))[:200] for s in failed[:3]],
        }
        signature = [s["tool"] for s in payload["steps"]]
        for row in self._rows():
            existing = row.get("payload", {})
            if [s.get("tool") for s in existing.get("steps", [])] == signature:
                scores, _method = rank(goal, [str(existing.get("goal", ""))], embedder=self.embedder)
                if scores and scores[0] >= 0.85:
                    return None  # already known; avoid duplicate memories
        confidence = 0.9 if all(s["verified"] for s in payload["steps"] if s["status"] == "succeeded") else 0.6
        try:
            self.store.add_memory(namespace=NAMESPACE, memory_type=kind, payload=payload,
                                  source="verified_outcome" if kind == "procedure" else "observed_failure",
                                  confidence=confidence if kind == "procedure" else 0.5)
        except ValueError:
            return None
        tools = ", ".join(t.removeprefix("senti_") for t in signature)
        return (f"Learned a working procedure ({tools})" if kind == "procedure"
                else f"Learned to avoid an approach that failed ({tools})")

    def recall(self, goal: str, *, limit: int = 4) -> list[dict[str, Any]]:
        rows = self._rows()
        if not rows or not isinstance(goal, str) or not goal.strip():
            return []
        documents = [str(r.get("payload", {}).get("goal", "")) for r in rows]
        scores, method = rank(goal, documents, embedder=self.embedder)
        threshold = 0.62 if method == "semantic" else 0.4
        ranked = sorted(zip(scores, range(len(rows))), key=lambda x: -x[0])
        output = []
        for score, index in ranked[:limit]:
            if score < threshold:
                break
            row = rows[index]
            output.append({"kind": row.get("memory_type"), "relevance": round(score, 3),
                           "learned_at": row.get("updated_at"),
                           **json.loads(json.dumps(row.get("payload", {}), ensure_ascii=False))})
        return output
