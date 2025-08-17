"""
Infrastructure Layer

Adapters for external systems and services.
"""

from .storage_adapter import MemoryDraftRepository
from .container import DraftContainer

__all__ = ["MemoryDraftRepository", "DraftContainer"]
