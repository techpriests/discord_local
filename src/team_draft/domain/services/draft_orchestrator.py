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
from .servant_service import ServantService
from .team_selection_service import TeamSelectionService


class DraftOrchestrator:
    """
    Core domain service that orchestrates draft lifecycle and workflow.
    
    Preserves all existing business logic while providing clean domain methods.
    """
    
    def __init__(self):
        self._servant_service = ServantService()
        self._team_selection_service = TeamSelectionService()
    
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
        
        # Initialize servant availability
        self._servant_service.initialize_servant_availability(draft)
        
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
    
    def prepare_thread_creation(self, draft: Draft) -> None:
        """Prepare thread creation for draft - preserves legacy naming logic"""
        team_format = f"{draft.team_size}v{draft.team_size}"
        
        # Generate unique thread name (legacy format)
        base_name = f"팀 드래프트 ({team_format})"
        thread_name = f"🏆 {base_name}"
        
        # Add timestamp if needed for uniqueness
        import time
        timestamp = int(time.time()) % 10000  # Last 4 digits
        
        # Store thread creation parameters
        draft.thread_name = thread_name
        draft.thread_ready_for_creation = True
    
    def perform_system_bans(self, draft: Draft) -> List[str]:
        """Perform automated system bans - preserves legacy algorithm"""
        return self._servant_service.perform_system_bans(draft)
    
    def complete_servant_ban_phase(self, draft: Draft) -> None:
        """Complete the entire servant ban phase (system + captain bans)"""
        # 1. Perform system bans
        system_bans = self.perform_system_bans(draft)
        
        # 2. Determine captain ban order via dice roll
        ban_order = self._captain_service.determine_captain_ban_order(draft)
        
        # 3. Initialize captain ban phase
        self._servant_service.initialize_captain_bans(draft)
    
    def apply_captain_ban(self, draft: Draft, captain_id: int, servant_name: str) -> bool:
        """Apply a captain ban"""
        return self._servant_service.apply_captain_ban(draft, captain_id, servant_name)
    
    def are_captain_bans_complete(self, draft: Draft) -> bool:
        """Check if all captain bans are complete"""
        return self._servant_service.are_captain_bans_complete(draft)
    
    def initialize_team_selection(self, draft: Draft, first_pick_captain: int) -> None:
        """Initialize team selection phase"""
        self._team_selection_service.initialize_team_selection(draft)
        draft.first_pick_captain = first_pick_captain
        draft.current_picking_captain = first_pick_captain
    
    def get_team_selection_pattern(self, team_size: int) -> List[Dict[str, int]]:
        """Get team selection pattern for given team size"""
        return self._team_selection_service.get_selection_pattern(team_size)
    
    def can_captain_pick_players(self, draft: Draft, captain_id: int) -> bool:
        """Check if captain can pick players in current round"""
        return self._team_selection_service.can_captain_pick(draft, captain_id)
    
    def get_available_picks_for_captain(self, draft: Draft, captain_id: int) -> int:
        """Get how many more picks a captain can make this round"""
        return self._team_selection_service.get_available_picks_count(draft, captain_id)
    
    def advance_team_selection_round(self, draft: Draft) -> bool:
        """Advance to next captain or round, returns True if continues"""
        return self._team_selection_service.advance_team_selection(draft)
    
    def is_team_selection_complete(self, draft: Draft) -> bool:
        """Check if team selection is complete"""
        return self._team_selection_service.is_team_selection_complete(draft)
    
    # =====================
    # Phase Transition Logic  
    # =====================
    
    def transition_to_servant_ban_phase(self, draft: Draft) -> None:
        """Transition from captain voting to servant ban phase"""
        if not draft.phase.can_transition_to(DraftPhase.SERVANT_BAN):
            raise InvalidPhaseTransitionError(f"Cannot transition from {draft.phase} to SERVANT_BAN")
        
        # Assign captains to teams
        if len(draft.captains) >= 2:
            draft.players[draft.captains[0]].assign_to_team(1)
            draft.players[draft.captains[1]].assign_to_team(2)
        
        draft.phase = DraftPhase.SERVANT_BAN
    
    def transition_to_servant_selection_phase(self, draft: Draft) -> None:
        """Transition from servant ban to servant selection phase"""
        if not draft.phase.can_transition_to(DraftPhase.SERVANT_SELECTION):
            raise InvalidPhaseTransitionError(f"Cannot transition from {draft.phase} to SERVANT_SELECTION")
        
        draft.phase = DraftPhase.SERVANT_SELECTION
    
    def check_servant_conflicts_and_transition(self, draft: Draft) -> bool:
        """
        Check for servant conflicts and transition appropriately.
        
        Returns:
            True if conflicts found (transition to RESELECTION), False if no conflicts (transition to TEAM_SELECTION)
        """
        if not draft.phase.can_transition_to(DraftPhase.SERVANT_RESELECTION):
            raise InvalidPhaseTransitionError(f"Cannot check conflicts from {draft.phase}")
        
        # Detect conflicts
        conflicts = self._servant_service.detect_servant_conflicts(draft)
        
        if conflicts:
            # Has conflicts - resolve with dice and then go to reselection for losers
            resolution_results = self._servant_service.resolve_servant_conflicts_with_dice(draft)
            
            # Log resolution results for debugging
            import logging
            logger = logging.getLogger(__name__)
            for servant, result in resolution_results.items():
                winner_id = result['winner_id']
                losers = result['losers']
                dice_rolls = result['dice_rolls']
                attempts = result['attempts']
                
                # Get player names for logging
                winner_name = next(
                    (p.username for p in draft.players.values() if p.user_id == winner_id), 
                    f"User{winner_id}"
                )
                loser_names = [
                    next((p.username for p in draft.players.values() if p.user_id == uid), f"User{uid}")
                    for uid in losers
                ]
                
                logger.info(
                    f"Conflict resolved for {servant}: {winner_name} won with dice roll {dice_rolls[winner_id]} "
                    f"(attempts: {attempts}). Losers need reselection: {', '.join(loser_names)}"
                )
            
            # Check if there are still users needing reselection
            if draft.conflicted_servants:
                # Some users need to reselect - go to reselection phase
                draft.phase = DraftPhase.SERVANT_RESELECTION
                
                # Apply automatic cloaking bans for reselection
                auto_bans = self._servant_service.apply_automatic_cloaking_bans_for_reselection(draft)
                
                return True
            else:
                # All conflicts resolved with no reselection needed - go to team selection
                # Determine first pick captain (can be enhanced with specific logic)
                if len(draft.captains) >= 2:
                    # For now, simple random or first captain
                    draft.first_pick_captain = draft.captains[0]
                
                draft.phase = DraftPhase.TEAM_SELECTION
                self.initialize_team_selection(draft, draft.first_pick_captain)
                
                return False
        else:
            # No conflicts - confirm all selections and go to team selection
            for user_id, player in draft.players.items():
                if not player.is_captain and player.selected_servant:
                    self._servant_service.confirm_servant_selection(draft, user_id)
            
            # Determine first pick captain (can be enhanced with specific logic)
            if len(draft.captains) >= 2:
                # For now, simple random or first captain
                draft.first_pick_captain = draft.captains[0]
            
            draft.phase = DraftPhase.TEAM_SELECTION
            self.initialize_team_selection(draft, draft.first_pick_captain)
            
            return False
    
    def transition_to_team_selection_phase(self, draft: Draft) -> None:
        """Transition from servant reselection to team selection phase"""
        if not draft.phase.can_transition_to(DraftPhase.TEAM_SELECTION):
            raise InvalidPhaseTransitionError(f"Cannot transition from {draft.phase} to TEAM_SELECTION")
        
        # Confirm remaining selections
        for user_id, player in draft.players.items():
            if not player.is_captain and player.selected_servant:
                self._servant_service.confirm_servant_selection(draft, user_id)
        
        # Determine first pick captain if not set
        if not draft.first_pick_captain and len(draft.captains) >= 2:
            draft.first_pick_captain = draft.captains[0]
        
        draft.phase = DraftPhase.TEAM_SELECTION
        self.initialize_team_selection(draft, draft.first_pick_captain)
    
    def transition_to_completed_phase(self, draft: Draft) -> None:
        """Transition to completed phase"""
        if not draft.phase.can_transition_to(DraftPhase.COMPLETED):
            raise InvalidPhaseTransitionError(f"Cannot transition from {draft.phase} to COMPLETED")
        
        draft.phase = DraftPhase.COMPLETED
    
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
        
        # Count votes - preserves existing logic with comprehensive logging
        vote_counts: Dict[int, int] = {}
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Captain selection finalization starting for draft with {len(draft.players)} players")
        
        # Log all votes received
        for voter_id, votes in captain_votes.items():
            if voter_id in draft.players:  # Only count votes from draft participants
                voter_name = next((p.username for p in draft.players.values() if p.user_id == voter_id), f"User{voter_id}")
                vote_names = []
                for captain_id in votes:
                    if captain_id in draft.players:  # Only count votes for draft participants
                        candidate_name = next((p.username for p in draft.players.values() if p.user_id == captain_id), f"User{captain_id}")
                        vote_names.append(candidate_name)
                        vote_counts[captain_id] = vote_counts.get(captain_id, 0) + 1
                
                logger.info(f"Captain selection: {voter_name} voted for: {', '.join(vote_names) if vote_names else 'no one'}")
        
        # Log vote tallies
        logger.info("Captain selection vote tallies:")
        for candidate_id, count in sorted(vote_counts.items(), key=lambda x: x[1], reverse=True):
            candidate_name = next((p.username for p in draft.players.values() if p.user_id == candidate_id), f"User{candidate_id}")
            logger.info(f"  {candidate_name}: {count} votes")
        
        # Select top 2 vote getters - preserves existing logic
        sorted_candidates = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        
        if len(sorted_candidates) < 2:
            # Fall back to first 2 players if not enough votes
            captain_ids = list(draft.players.keys())[:2]
            logger.warning(
                f"Captain selection: Not enough vote candidates ({len(sorted_candidates)}), "
                f"falling back to first 2 players"
            )
        else:
            captain_ids = [candidate[0] for candidate in sorted_candidates[:2]]
        
        # Log final captain selection
        captain_names = []
        for captain_id in captain_ids:
            captain_name = next((p.username for p in draft.players.values() if p.user_id == captain_id), f"User{captain_id}")
            captain_names.append(captain_name)
            votes_received = vote_counts.get(captain_id, 0)
            logger.info(f"Captain selection: {captain_name} selected as captain with {votes_received} votes")
        
        logger.info(f"Captain selection complete: Final captains are {', '.join(captain_names)}")
        
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
