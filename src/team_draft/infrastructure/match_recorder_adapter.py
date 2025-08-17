"""
Match Recorder Adapter

Adapter for existing match recording system.
"""

from typing import Optional
from ..application.interfaces import IMatchRecorder
from ..domain.entities.draft import Draft
from src.services.match_recorder import MatchRecorder, PlayerFeature, MatchRecord


class MatchRecorderAdapter(IMatchRecorder):
    """
    Adapter for existing match recorder system.
    
    Preserves existing match recording functionality while providing clean interface.
    """
    
    def __init__(self):
        self._recorder = MatchRecorder()
    
    async def record_match(self, draft: Draft, winner: Optional[int], score: Optional[str]) -> None:
        """Record match result using existing match recorder"""
        try:
            # Convert draft to match record format
            match_record = self._convert_draft_to_match_record(draft, winner, score)
            
            # Use existing recorder
            self._recorder.record_match(match_record)
            
        except Exception as e:
            # Log error but don't fail the operation
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to record match: {e}")
    
    def _convert_draft_to_match_record(
        self, 
        draft: Draft, 
        winner: Optional[int], 
        score: Optional[str]
    ) -> MatchRecord:
        """Convert draft to match record format"""
        import time
        
        # Convert players to PlayerFeature format
        team1_players = []
        team2_players = []
        
        for player in draft.players.values():
            player_feature = PlayerFeature(
                user_id=player.user_id,
                display_name=player.username,
                servant=player.selected_servant,
                is_captain=player.is_captain,
                pick_order=None  # Could be enhanced with pick order tracking
            )
            
            if player.team == 1:
                team1_players.append(player_feature)
            elif player.team == 2:
                team2_players.append(player_feature)
        
        # Create match record
        match_record = MatchRecord(
            match_id=draft.match_id or draft.draft_id,
            timestamp=time.time(),
            guild_id=draft.guild_id,
            channel_id=draft.channel_id,
            team_size=draft.team_size,
            captains=draft.captains.copy(),
            team1=team1_players,
            team2=team2_players,
            bans=list(draft.banned_servants),
            winner=winner,
            score=score,
            sim_session=draft.simulation_session_id,
            author_id=draft.simulation_author_id,
            is_simulation=draft.is_simulation,
            draft_type="manual" if not draft.auto_balance_result else "auto",
            balance_algorithm=draft.auto_balance_result.get("algorithm") if draft.auto_balance_result else None,
            predicted_balance_score=draft.auto_balance_result.get("balance_score") if draft.auto_balance_result else None,
            predicted_confidence=draft.auto_balance_result.get("confidence") if draft.auto_balance_result else None,
            auto_balance_used=draft.auto_balance_result is not None
        )
        
        return match_record
