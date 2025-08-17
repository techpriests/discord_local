"""
Draft Orchestrator Domain Service

Coordinates the overall draft workflow and manages phase transitions.
Contains core business logic extracted from the original TeamDraftCommands.
"""

import time
import uuid
from typing import List, Optional, Dict, Any
from ..entities.draft import Draft
from ..entities.draft_phase import DraftPhase
from ..entities.player import Player
from ..exceptions import (
    InvalidDraftStateError, 
    DraftFullError, 
    PlayerAlreadyExistsError,
    InvalidPhaseTransitionError
)


class DraftOrchestrator:
    """
    Core domain service that orchestrates draft lifecycle and workflow.
    
    Preserves all existing business logic while providing clean domain methods.
    """
    
    def create_draft(
        self, 
        channel_id: int, 
        guild_id: int, 
        team_size: int = 6,
        started_by_user_id: Optional[int] = None,
        is_test_mode: bool = False
    ) -> Draft:
        """Create a new draft session"""
        if team_size < 1:
            raise ValueError("Team size must be positive")
        
        draft = Draft(
            channel_id=channel_id,
            guild_id=guild_id,
            team_size=team_size,
            started_by_user_id=started_by_user_id,
            is_test_mode=is_test_mode
        )
        
        return draft
    
    def create_join_based_draft(
        self,
        channel_id: int,
        guild_id: int, 
        total_players: int,
        started_by_user_id: Optional[int] = None
    ) -> Draft:
        """Create a draft that starts when enough players join"""
        if total_players < 2 or total_players % 2 != 0:
            raise ValueError("Total players must be even and at least 2")
        
        team_size = total_players // 2
        draft = self.create_draft(
            channel_id=channel_id,
            guild_id=guild_id,
            team_size=team_size,
            started_by_user_id=started_by_user_id
        )
        
        draft.join_target_total_players = total_players
        return draft
    
    def add_player_to_draft(self, draft: Draft, user_id: int, username: str) -> None:
        """Add a player to the draft - preserves existing logic"""
        if draft.is_full:
            raise DraftFullError("Draft is already full")
        
        if user_id in draft.players:
            raise PlayerAlreadyExistsError(f"Player {user_id} is already in the draft")
        
        draft.add_player(user_id, username)
    
    def remove_player_from_draft(self, draft: Draft, user_id: int) -> None:
        """Remove a player from the draft"""
        if draft.phase != DraftPhase.WAITING:
            raise InvalidDraftStateError("Cannot remove players after draft has started")
        
        draft.remove_player(user_id)
    
    def can_start_draft(self, draft: Draft) -> bool:
        """Check if draft can be started - preserves existing logic"""
        return draft.can_start
    
    def start_captain_voting(self, draft: Draft) -> None:
        """Start the captain voting phase - preserves existing logic"""
        if not draft.can_start:
            raise InvalidDraftStateError("Draft cannot be started - not enough players")
        
        if draft.phase != DraftPhase.WAITING:
            raise InvalidDraftStateError("Draft is not in waiting phase")
        
        # Advance to captain voting phase
        draft.advance_phase(DraftPhase.CAPTAIN_VOTING)
        draft.captain_voting_start_time = time.time()
        
        # Initialize voting progress for all players
        for user_id in draft.players.keys():
            draft.captain_voting_progress[user_id] = 0
    
    def finalize_captain_selection(
        self, 
        draft: Draft, 
        captain_votes: Dict[int, List[int]]
    ) -> List[int]:
        """
        Finalize captain selection based on votes - preserves existing algorithm
        
        Args:
            draft: The draft session
            captain_votes: Dict of user_id -> list of voted captain IDs
            
        Returns:
            List of selected captain IDs
        """
        if draft.phase != DraftPhase.CAPTAIN_VOTING:
            raise InvalidDraftStateError("Not in captain voting phase")
        
        # Count votes - preserves existing logic
        vote_counts: Dict[int, int] = {}
        for voter_id, votes in captain_votes.items():
            if voter_id in draft.players:  # Only count votes from draft participants
                for captain_id in votes:
                    if captain_id in draft.players:  # Only count votes for draft participants
                        vote_counts[captain_id] = vote_counts.get(captain_id, 0) + 1
        
        # Select top 2 vote getters - preserves existing logic
        sorted_candidates = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        
        if len(sorted_candidates) < 2:
            # Fall back to first 2 players if not enough votes
            captain_ids = list(draft.players.keys())[:2]
        else:
            captain_ids = [candidate[0] for candidate in sorted_candidates[:2]]
        
        # Set captains in draft
        draft.set_captains(captain_ids)
        
        return captain_ids
    
    def start_servant_ban_phase(self, draft: Draft) -> None:
        """Start servant ban phase - preserves existing logic"""
        if draft.phase != DraftPhase.CAPTAIN_VOTING:
            raise InvalidDraftStateError("Must complete captain voting first")
        
        if not draft.teams.both_have_captains:
            raise InvalidDraftStateError("Both teams must have captains")
        
        draft.advance_phase(DraftPhase.SERVANT_BAN)
        
        # Initialize ban progress for captains
        for captain_id in draft.captains:
            draft.captain_ban_progress[captain_id] = False
    
    def complete_servant_ban_phase(self, draft: Draft) -> None:
        """Complete servant ban phase and advance to selection"""
        if draft.phase != DraftPhase.SERVANT_BAN:
            raise InvalidDraftStateError("Not in servant ban phase")
        
        # Check if all captains have completed banning
        all_captains_done = all(
            draft.captain_ban_progress.get(captain_id, False) 
            for captain_id in draft.captains
        )
        
        if not all_captains_done:
            raise InvalidDraftStateError("Not all captains have completed banning")
        
        draft.advance_phase(DraftPhase.SERVANT_SELECTION)
        draft.selection_start_time = time.time()
        
        # Initialize selection progress for all players
        for user_id in draft.players.keys():
            draft.selection_progress[user_id] = False
    
    def start_servant_reselection(self, draft: Draft) -> None:
        """Start servant reselection phase - preserves existing logic"""
        if draft.phase != DraftPhase.SERVANT_SELECTION:
            raise InvalidDraftStateError("Must complete servant selection first")
        
        draft.advance_phase(DraftPhase.SERVANT_RESELECTION)
        draft.reselection_start_time = time.time()
        draft.reselection_round += 1
        
        # Reset selection progress for conflicted players only
        # (This preserves the existing logic for handling servant conflicts)
        for user_id in draft.conflicted_servants.keys():
            draft.selection_progress[user_id] = False
    
    def complete_servant_selection(self, draft: Draft) -> None:
        """Complete servant selection and advance to team selection"""
        current_phase = draft.phase
        if current_phase not in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
            raise InvalidDraftStateError("Not in a servant selection phase")
        
        # Check if all players have completed selection
        all_players_done = all(
            draft.selection_progress.get(user_id, False) 
            for user_id in draft.players.keys()
        )
        
        if not all_players_done:
            # Check for conflicts that need reselection
            if current_phase == DraftPhase.SERVANT_SELECTION and len(draft.conflicted_servants) > 0:
                self.start_servant_reselection(draft)
                return
            else:
                raise InvalidDraftStateError("Not all players have completed selection")
        
        draft.advance_phase(DraftPhase.TEAM_SELECTION)
    
    def start_team_selection(self, draft: Draft, first_pick_captain_id: int) -> None:
        """Start team selection phase - preserves existing logic"""
        if draft.phase != DraftPhase.TEAM_SELECTION:
            # Allow advancing from servant phases if ready
            if draft.phase in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
                self.complete_servant_selection(draft)
            else:
                raise InvalidDraftStateError("Cannot start team selection from current phase")
        
        if not draft.is_captain(first_pick_captain_id):
            raise ValueError("First pick must be a captain")
        
        draft.start_team_selection(first_pick_captain_id)
    
    def complete_team_selection(self, draft: Draft) -> None:
        """Complete team selection and finish draft"""
        if draft.phase != DraftPhase.TEAM_SELECTION:
            raise InvalidDraftStateError("Not in team selection phase")
        
        if not draft.teams.is_complete:
            raise InvalidDraftStateError("Teams are not complete")
        
        draft.advance_phase(DraftPhase.COMPLETED)
    
    def can_advance_to_next_phase(self, draft: Draft) -> bool:
        """Check if draft can advance to next phase - preserves existing logic"""
        if draft.phase == DraftPhase.WAITING:
            return draft.can_start
        elif draft.phase == DraftPhase.CAPTAIN_VOTING:
            return len(draft.captains) == 2
        elif draft.phase == DraftPhase.SERVANT_BAN:
            return all(draft.captain_ban_progress.get(cid, False) for cid in draft.captains)
        elif draft.phase == DraftPhase.SERVANT_SELECTION:
            return all(draft.selection_progress.get(uid, False) for uid in draft.players.keys())
        elif draft.phase == DraftPhase.SERVANT_RESELECTION:
            return all(draft.selection_progress.get(uid, False) for uid in draft.conflicted_servants.keys())
        elif draft.phase == DraftPhase.TEAM_SELECTION:
            return draft.teams.is_complete
        
        return False
    
    def force_advance_phase(self, draft: Draft) -> DraftPhase:
        """Force advance to next phase - for admin/timeout scenarios"""
        current_phase = draft.phase
        
        if current_phase == DraftPhase.WAITING:
            self.start_captain_voting(draft)
        elif current_phase == DraftPhase.CAPTAIN_VOTING:
            # Auto-select first 2 players as captains
            captain_ids = list(draft.players.keys())[:2]
            draft.set_captains(captain_ids)
            self.start_servant_ban_phase(draft)
        elif current_phase == DraftPhase.SERVANT_BAN:
            # Mark all captains as done with banning
            for captain_id in draft.captains:
                draft.captain_ban_progress[captain_id] = True
            self.complete_servant_ban_phase(draft)
        elif current_phase == DraftPhase.SERVANT_SELECTION:
            # Mark all players as done with selection
            for user_id in draft.players.keys():
                draft.selection_progress[user_id] = True
            self.complete_servant_selection(draft)
        elif current_phase == DraftPhase.SERVANT_RESELECTION:
            # Mark conflicted players as done
            for user_id in draft.conflicted_servants.keys():
                draft.selection_progress[user_id] = True
            self.complete_servant_selection(draft)
        elif current_phase == DraftPhase.TEAM_SELECTION:
            self.complete_team_selection(draft)
        
        return draft.phase
    
    def get_phase_summary(self, draft: Draft) -> Dict[str, Any]:
        """Get summary of current phase progress - for UI display"""
        return draft.get_phase_progress()
    
    def validate_draft_state(self, draft: Draft) -> List[str]:
        """Validate current draft state - preserves existing validation logic"""
        return draft.validate_state()
