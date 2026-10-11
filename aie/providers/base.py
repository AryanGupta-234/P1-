"""Read-only provider interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterator
from aie.contracts import AIEEvent


class ObserverProvider(ABC):
    name: str

    @abstractmethod
    def collect_snapshot(self) -> Iterator[AIEEvent]:
        """Return a read-only point-in-time snapshot."""
        raise NotImplementedError
