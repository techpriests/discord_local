"""
Storage Adapter

Implementation of draft repository interface using in-memory storage.
Preserves existing storage patterns while providing clean interface.
"""

from typing import Dict, List, Optional
from ..application.interfaces import IDraftRepository
from ..domain.entities.draft import Draft


class MemoryDraftRepository(IDraftRepository):
    """
    In-memory implementation of draft repository.
    
    Preserves the existing pattern from TeamDraftCommands.active_drafts
    """
    
    def __init__(self):
        self._drafts: Dict[int, Draft] = {}  # channel_id -> Draft
    
    async def save_draft(self, draft: Draft) -> None:
        """Save a draft to memory storage"""
        self._drafts[draft.channel_id] = draft
    
    async def get_draft(self, channel_id: int) -> Optional[Draft]:
        """Get draft by channel ID"""
        return self._drafts.get(channel_id)
    
    async def delete_draft(self, channel_id: int) -> None:
        """Delete a draft from storage"""
        if channel_id in self._drafts:
            del self._drafts[channel_id]
    
    async def get_active_drafts(self) -> List[Draft]:
        """Get all active drafts"""
        return list(self._drafts.values())
    
    def get_draft_count(self) -> int:
        """Get number of active drafts"""
        return len(self._drafts)
    
    def clear_all_drafts(self) -> None:
        """Clear all drafts (for testing/cleanup)"""
        self._drafts.clear()
    
    def has_draft(self, channel_id: int) -> bool:
        """Check if draft exists for channel"""
        return channel_id in self._drafts
