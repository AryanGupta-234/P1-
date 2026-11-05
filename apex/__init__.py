"""APEX: an independent, local-first Windows assistant runtime."""

from apex.config import ApexSettings
from apex.host import ApexService
from apex.runtime import ApexHost

__all__ = ["ApexHost", "ApexService", "ApexSettings"]
__version__ = "0.1.0"
