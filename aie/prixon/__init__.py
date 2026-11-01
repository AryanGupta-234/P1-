"""PRIXON identity/runtime facade over the existing AIE intelligence engines.

The package deliberately reuses AIE model, memory, knowledge and orchestration
components. It does not fork the inference backend or create duplicate stores.
"""
from aie.prixon.identity import (
    DEFAULT_PRIXON_IDENTITY,
    FoundationLineage,
    PRIXONIdentity,
)
from aie.prixon.runtime import PRIXONRuntime, PRIXONTurn

__all__ = [
    "DEFAULT_PRIXON_IDENTITY",
    "FoundationLineage",
    "PRIXONIdentity",
    "PRIXONRuntime",
    "PRIXONTurn",
]
