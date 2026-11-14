"""Semantic understanding primitives: local embeddings, similarity ranking and fuzzy fallback.

SENTI does not route requests through hand-written keyword or synonym tables. Meaning is
compared with a local embedding model (``nomic-embed-text`` through Ollama by default).
When embeddings are unavailable the host degrades to a generic fuzzy lexical score, which
uses only the words that actually appear in the request and the candidate text.
"""
from __future__ import annotations

import difflib
import hashlib
import math
import re
import threading
from collections import OrderedDict
from typing import Callable, Iterable, Protocol, Sequence

# nomic-embed-text is trained with task prefixes; other models simply see a short prefix.
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "


class EmbedFunction(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    normalized = text.casefold().replace("wi-fi", "wifi")
    words = {w for w in _WORD.findall(normalized) if len(w) > 1}
    stems = set()
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            stems.add(word[:-3] + "y")
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            stems.add(word[:-1])
        elif len(word) > 5 and word.endswith("ing"):
            stems.add(word[:-3])
    return words | stems


def lexical_score(query: str, document: str) -> float:
    """Generic fuzzy relevance in [0, 1] without any vocabulary tables.

    Combines exact token overlap with per-token fuzzy matching (typos such as "blutooth").
    Very common short words carry little information, so tokens shorter than three
    characters are ignored on the query side.
    """
    q = {t for t in tokens(query) if len(t) >= 3}
    d = tokens(document)
    if not q or not d:
        return 0.0
    hits = 0.0
    for term in q:
        if term in d:
            hits += 1.0
            continue
        best = max((difflib.SequenceMatcher(None, term, other).ratio() for other in d
                    if abs(len(other) - len(term)) <= 3), default=0.0)
        if best >= 0.82:
            hits += best * 0.8
    return hits / len(q)


class Embedder:
    """Thread-safe embedding cache in front of an embedding function.

    The cache key is a digest of the prefixed text, so identical tool descriptions or
    memories are embedded once per process. Failures mark the embedder unavailable for a
    short cool-down instead of slowing every request.
    """

    def __init__(self, embed: EmbedFunction | None, *, max_entries: int = 4_096,
                 retry_after_failures: int = 20, clock: Callable[[], float] | None = None):
        import time
        self._embed = embed
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries
        self._clock = clock or time.monotonic
        self._disabled_until = 0.0
        self._cooldown = float(retry_after_failures)

    @property
    def available(self) -> bool:
        return self._embed is not None and self._clock() >= self._disabled_until

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []
        if not self.available:
            return None
        keys = [self._key(t) for t in texts]
        with self._lock:
            missing = [(i, t) for i, (k, t) in enumerate(zip(keys, texts)) if k not in self._cache]
        if missing:
            try:
                vectors: list[list[float]] = []
                for start in range(0, len(missing), 64):
                    batch = [t for _i, t in missing[start:start + 64]]
                    vectors.extend(self._embed(batch))  # type: ignore[misc]
            except Exception:  # noqa: BLE001 - semantic layer degrades to lexical matching.
                self._disabled_until = self._clock() + self._cooldown
                return None
            with self._lock:
                for (index, _text), vector in zip(missing, vectors):
                    self._cache[keys[index]] = vector
                while len(self._cache) > self._max:
                    self._cache.popitem(last=False)
        with self._lock:
            result = [self._cache.get(k) for k in keys]
        if any(v is None for v in result):
            return None
        return result  # type: ignore[return-value]

    def query(self, text: str) -> list[float] | None:
        vectors = self.embed([QUERY_PREFIX + text])
        return vectors[0] if vectors else None

    def documents(self, texts: list[str]) -> list[list[float]] | None:
        return self.embed([DOCUMENT_PREFIX + t for t in texts])


def rank(query: str, documents: Iterable[str], *, embedder: Embedder | None = None,
         lexical_weight: float = 0.25) -> tuple[list[float], str]:
    """Score every document for the query. Returns (scores, method)."""
    docs = list(documents)
    if not docs:
        return [], "none"
    if embedder is not None and embedder.available:
        q = embedder.query(query)
        d = embedder.documents(docs) if q is not None else None
        if q is not None and d is not None:
            scores = [
                (1.0 - lexical_weight) * cosine(q, vec) + lexical_weight * lexical_score(query, doc)
                for vec, doc in zip(d, docs)
            ]
            return scores, "semantic"
    return [lexical_score(query, doc) for doc in docs], "lexical"
