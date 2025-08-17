"""
Roster Service Adapter

Adapter for existing roster storage system.
"""

from typing import Optional
from ..application.interfaces import IRosterService
from src.services.roster_store import RosterStore


class RosterServiceAdapter(IRosterService):
    """
    Adapter for existing roster storage system.
    
    Provides clean interface for player rating management.
    """
    
    def __init__(self):
        self._roster_store = RosterStore()
    
    async def get_player_rating(self, user_id: int, guild_id: int) -> Optional[float]:
        """Get player rating from roster"""
        try:
            players = self._roster_store.load(guild_id)
            
            for player in players:
                if player.user_id == user_id:
                    return player.rating
            
            return None
            
        except Exception:
            return None
    
    async def update_player_rating(self, user_id: int, guild_id: int, rating: float) -> None:
        """Update player rating in roster"""
        try:
            players = self._roster_store.load(guild_id)
            
            # Find existing player or create new one
            player_found = False
            for player in players:
                if player.user_id == user_id:
                    player.rating = rating
                    player_found = True
                    break
            
            if not player_found:
                # Create new player entry
                from src.services.roster_store import RosterPlayer
                new_player = RosterPlayer(
                    user_id=user_id,
                    display_name=str(user_id),  # Will be updated with actual name later
                    rating=rating
                )
                players.append(new_player)
            
            # Save updated roster
            self._roster_store.save(guild_id, players)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update player rating: {e}")
    
    def get_roster_store(self) -> RosterStore:
        """Get underlying roster store for advanced operations"""
        return self._roster_store
