"""Review-only memory consolidation proposals.

The consolidator never edits, merges, deletes, reweights or retrains memory records.
It only identifies likely duplicates/near-duplicates for explicit user review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aie.memory.models import MemoryKind
from aie.memory.store import MemoryStore, StoredMemory

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]{1,39}")


@dataclass(frozen=True, slots=True)
class ConsolidationProposal:
    memory_ids: tuple[str, str]
    kind: MemoryKind
    similarity: float
    reason: str
    recommended_action: str = "review_manually"


def _features(item: StoredMemory) -> tuple[set[str], set[str]]:
    content = set(_TOKEN.findall(item.memory.content.lower()))
    tags = set(item.memory.tags)
    return content, tags


def _similarity(left: StoredMemory, right: StoredMemory) -> float:
    left_tokens, left_tags = _features(left)
    right_tokens, right_tags = _features(right)
    if not left_tokens and not right_tokens:
        content_score = 1.0
    elif not left_tokens or not right_tokens:
        content_score = 0.0
    else:
        content_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    if not left_tags and not right_tags:
        tag_score = 1.0
    elif not left_tags or not right_tags:
        tag_score = 0.0
    else:
        tag_score = len(left_tags & right_tags) / len(left_tags | right_tags)

    return (0.85 * content_score) + (0.15 * tag_score)


def generate_consolidation_proposals(
    store: MemoryStore,
    *,
    kind: MemoryKind | None = None,
    include_sensitive: bool = False,
    max_memories: int = 300,
    max_proposals: int = 100,
    similarity_threshold: float = 0.82,
) -> tuple[ConsolidationProposal, ...]:
    """Return bounded candidate pairs without changing any memory state."""
    if not 1 <= max_memories <= 1000:
        raise ValueError("max_memories must be between 1 and 1000")
    if not 1 <= max_proposals <= 500:
        raise ValueError("max_proposals must be between 1 and 500")
    if not 0.5 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between 0.5 and 1")

    memories = store.list_memories(
        kind=kind,
        include_sensitive=include_sensitive,
        include_superseded=False,
        include_expired=False,
        limit=max_memories,
    )
    proposals: list[ConsolidationProposal] = []
    for index, left in enumerate(memories):
        for right in memories[index + 1:]:
            if left.memory.kind != right.memory.kind:
                continue
            score = _similarity(left, right)
            if score < similarity_threshold:
                continue
            proposals.append(
                ConsolidationProposal(
                    memory_ids=(left.memory.memory_id, right.memory.memory_id),
                    kind=left.memory.kind,
                    similarity=round(score, 4),
                    reason="High lexical/tag overlap among active memories.",
                )
            )

    proposals.sort(
        key=lambda item: (item.similarity, item.memory_ids),
        reverse=True,
    )
    return tuple(proposals[:max_proposals])
