"""Deterministic in-process event fan-out for AIE observation pipelines."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from aie.contracts import AIEEvent


class EventSink(Protocol):
    def __call__(self, events: Iterable[AIEEvent]) -> int:
        """Consume an ordered batch and return the number durably handled."""


class EventBus:
    """Bounded synchronous event fan-out with explicit sink ordering.

    The bus owns no background threads or unbounded queue. Publication preserves the
    input order for every sink. A sink exception propagates to the caller rather than
    silently losing durable evidence.
    """

    def __init__(self, *, max_batch_size: int = 2_000) -> None:
        if not 1 <= max_batch_size <= 10_000:
            raise ValueError("max_batch_size must be between 1 and 10000")
        self.max_batch_size = max_batch_size
        self._sinks: list[tuple[str, EventSink]] = []

    def subscribe(self, name: str, sink: EventSink) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("sink name must be non-empty")
        if not callable(sink):
            raise ValueError("sink must be callable")
        if any(existing == name for existing, _ in self._sinks):
            raise ValueError(f"duplicate event sink: {name}")
        self._sinks.append((name, sink))

    @property
    def sink_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._sinks)

    def publish(self, events: Iterable[AIEEvent]) -> dict[str, int]:
        batch = tuple(events)
        if len(batch) > self.max_batch_size:
            raise ValueError(
                f"event batch exceeds the {self.max_batch_size} event limit"
            )
        if not batch or not self._sinks:
            return {}

        results: dict[str, int] = {}
        for name, sink in self._sinks:
            result = sink(batch)
            if not isinstance(result, int) or isinstance(result, bool) or result < 0:
                raise TypeError("event sink must return a non-negative integer")
            results[name] = result
        return results
