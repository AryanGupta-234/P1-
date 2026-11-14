"""SENTI: an independent, local-first Windows assistant runtime."""

from senti.config import SentiSettings
from senti.host import SentiService
from senti.runtime import SentiHost

__all__ = ["SentiHost", "SentiService", "SentiSettings"]
__version__ = "0.2.0"
