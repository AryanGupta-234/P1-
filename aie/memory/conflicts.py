"""Conservative lexical conflict candidates for explicit user review only."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aie.memory.models import MemoryKind
from aie.memory.store import MemoryStore, StoredMemory

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]{1,39}")

_OPPOSITES = (
    ("always", "never"),
    ("enable", "disable"),
    ("enabled", "disabled"),
    ("allow", "deny"),
    ("allowed", "blocked"),
    ("include", "exclude"),
    ("keep", "remove"),
    ("retain", "delete"),
    ("connect", "disconnect"),
    ("accept", "reject"),
    ("increase", "decrease"),
    ("raise", "lower"),
    ("before", "after"),
    ("on", "off"),
    ("true", "false"),
    ("use", "avoid"),
    ("prefer", "avoid"),
)


@dataclass(frozen=True, slots=True)
class MemoryConflictProposal:
    memory_ids: tuple[str, str]
    kind: MemoryKind
    shared_context_tokens: tuple[str, ...]
    opposing_terms: tuple[str, str]
    reason: str
    recommended_action: str = "review_manually"


def _tokens(item: StoredMemory) -> set[str]:
    return set(_TOKEN.findall(item.memory.content.lower()))


def generate_conflict_proposals(
    store: MemoryStore,
    *,
    kind: MemoryKind | None = None,
    include_sensitive: bool = False,
    max_memories: int = 300,
    max_proposals: int = 100,
    minimum_shared_tokens: int = 1,
) -> tuple[MemoryConflictProposal, ...]:
    """Flag explicit opposite lexical markers in records sharing substantive context.

    This is not natural-language contradiction resolution. Negation, modality,
    temporality, subject scope and factual entailment are not inferred. The queue
    intentionally favors false negatives over treating ambiguous phrasing as conflict.
    """
    if not 1 <= max_memories <= 1000:
        raise ValueError("max_memories must be between 1 and 1000")
    if not 1 <= max_proposals <= 500:
        raise ValueError("max_proposals must be between 1 and 500")
    if not 1 <= minimum_shared_tokens <= 10:
        raise ValueError("minimum_shared_tokens must be between 1 and 10")

    memories = store.list_memories(
        kind=kind,
        include_sensitive=include_sensitive,
        include_superseded=False,
        include_expired=False,
        limit=max_memories,
    )
    features = {item.memory.memory_id: _tokens(item) for item in memories}
    proposals: list[MemoryConflictProposal] = []
    for index, left in enumerate(memories):
        left_tokens = features[left.memory.memory_id]
        for right in memories[index + 1:]:
            if left.memory.kind != right.memory.kind:
                continue
            right_tokens = features[right.memory.memory_id]
            found: list[tuple[str, str]] = []
            for first, second in _OPPOSITES:
                if (first in left_tokens and second in right_tokens) or (
                    second in left_tokens and first in right_tokens
                ):
                    found.append((first, second))
            if not found:
                continue

            markers = {term for pair in found for term in pair}
            common = tuple(sorted((left_tokens & right_tokens) - markers))
            if len(common) < minimum_shared_tokens:
                continue
            pair = sorted((left.memory.memory_id, right.memory.memory_id))
            for first, second in found:
                proposals.append(
                    MemoryConflictProposal(
                        memory_ids=(pair[0], pair[1]),
                        kind=left.memory.kind,
                        shared_context_tokens=common[:20],
                        opposing_terms=(first, second),
                        reason=(
                            "Possible lexical polarity conflict only; inspect both "
                            "records and their dates before deciding."
                        ),
                    )
                )

    proposals.sort(
        key=lambda item: (
            len(item.shared_context_tokens),
            item.opposing_terms,
            item.memory_ids,
        ),
        reverse=True,
    )
    unique: list[MemoryConflictProposal] = []
    seen: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for proposal in proposals:
        key = (proposal.memory_ids, proposal.opposing_terms)
        if key in seen:
            continue
        seen.add(key)
        unique.append(proposal)
        if len(unique) >= max_proposals:
            break
    return tuple(unique)
