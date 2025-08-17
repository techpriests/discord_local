"""
Validation Service - Domain Service

Handles business rule validation and constraint checking.
Preserves all existing validation logic and rules.
"""

from typing import List, Dict, Optional, Set
from ..entities.draft import Draft
from ..entities.draft_phase import DraftPhase
from ..entities.player import Player
from ..exceptions import ValidationError


class ValidationService:
    """
    Domain service for validation operations.
    
    Preserves all existing validation rules and business constraints.
    """
    
    def validate_draft_creation(
        self, 
        channel_id: int, 
        guild_id: int, 
        team_size: int
    ) -> List[str]:
        """Validate draft creation parameters - preserves existing constraints"""
        errors = []
        
        if channel_id <= 0:
            errors.append("Invalid channel ID")
        
        if guild_id <= 0:
            errors.append("Invalid guild ID")
        
        if team_size < 1:
            errors.append("Team size must be positive")
        
        # Preserve existing team size constraints from original code
        if team_size not in [2, 3, 5, 6]:
            errors.append("Team size must be 2, 3, 5, or 6 (for 2v2, 3v3, 5v5, or 6v6)")
        
        return errors
    
    def validate_join_based_draft(self, total_players: int) -> List[str]:
        """Validate join-based draft parameters - preserves existing constraints"""
        errors = []
        
        if total_players <= 0:
            errors.append("Total players must be positive")
        
        if total_players % 2 != 0:
            errors.append("Total players must be even")
        
        # Preserve existing team size constraints (total_players // 2 must be in [2,3,5,6])
        team_size = total_players // 2
        if team_size not in [2, 3, 5, 6]:
            errors.append("Team size must be 2, 3, 5, or 6 (total players: 4, 6, 10, or 12)")
        
        return errors
    
    def validate_player_addition(self, draft: Draft, user_id: int, username: str) -> List[str]:
        """Validate adding a player to draft - preserves existing validation"""
        errors = []
        
        if user_id <= 0:
            errors.append("Invalid user ID")
        
        if not username or not username.strip():
            errors.append("Username cannot be empty")
        
        if draft.is_full:
            errors.append("Draft is already full")
        
        if user_id in draft.players:
            errors.append("Player is already in the draft")
        
        if draft.phase != DraftPhase.WAITING:
            errors.append("Cannot add players after draft has started")
        
        return errors
    
    def validate_player_removal(self, draft: Draft, user_id: int) -> List[str]:
        """Validate removing a player from draft"""
        errors = []
        
        if user_id not in draft.players:
            errors.append("Player is not in the draft")
        
        if draft.phase != DraftPhase.WAITING:
            errors.append("Cannot remove players after draft has started")
        
        return errors
    
    def validate_captain_vote(
        self, 
        draft: Draft, 
        voter_id: int, 
        candidate_id: int,
        current_votes: Optional[Set[int]] = None
    ) -> List[str]:
        """Validate captain voting - preserves existing validation logic"""
        errors = []
        
        if draft.phase != DraftPhase.CAPTAIN_VOTING:
            errors.append("Not in captain voting phase")
        
        if voter_id not in draft.players:
            errors.append("Voter is not in the draft")
        
        if candidate_id not in draft.players:
            errors.append("Candidate is not in the draft")
        
        # Check vote limit
        if current_votes and len(current_votes) >= 2 and candidate_id not in current_votes:
            errors.append("Maximum 2 votes allowed")
        
        return errors
    
    def validate_captain_selection(self, draft: Draft, captain_ids: List[int]) -> List[str]:
        """Validate captain selection"""
        errors = []
        
        if len(captain_ids) != 2:
            errors.append("Must select exactly 2 captains")
        
        for captain_id in captain_ids:
            if captain_id not in draft.players:
                errors.append(f"Captain {captain_id} is not in the draft")
        
        if len(set(captain_ids)) != len(captain_ids):
            errors.append("Cannot select the same person as both captains")
        
        return errors
    
    def validate_servant_ban(self, draft: Draft, captain_id: int, servant_name: str) -> List[str]:
        """Validate servant banning - preserves existing validation logic"""
        errors = []
        
        if draft.phase != DraftPhase.SERVANT_BAN:
            errors.append("Not in servant ban phase")
        
        if not draft.is_captain(captain_id):
            errors.append("Only captains can ban servants")
        
        if not servant_name or not servant_name.strip():
            errors.append("Servant name cannot be empty")
        
        if servant_name not in draft.available_servants:
            errors.append(f"Servant {servant_name} is not available")
        
        if servant_name in draft.banned_servants:
            errors.append(f"Servant {servant_name} is already banned")
        
        # Check if captain has already banned
        if draft.captain_ban_progress.get(captain_id, False):
            errors.append("Captain has already completed their ban")
        
        return errors
    
    def validate_servant_selection(
        self, 
        draft: Draft, 
        user_id: int, 
        servant_name: str
    ) -> List[str]:
        """Validate servant selection - preserves existing validation logic"""
        errors = []
        
        if draft.phase not in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
            errors.append("Not in servant selection phase")
        
        if user_id not in draft.players:
            errors.append("Player is not in the draft")
        
        if not servant_name or not servant_name.strip():
            errors.append("Servant name cannot be empty")
        
        if not draft.is_servant_available(servant_name):
            errors.append(f"Servant {servant_name} is not available")
        
        # Check if another player has already selected this servant
        for player in draft.players.values():
            if player.user_id != user_id and player.selected_servant == servant_name:
                errors.append(f"Servant {servant_name} is already selected by {player.username}")
        
        # Check if player has already completed selection
        if draft.selection_progress.get(user_id, False):
            if draft.phase == DraftPhase.SERVANT_SELECTION:
                errors.append("Player has already completed servant selection")
            elif draft.phase == DraftPhase.SERVANT_RESELECTION:
                # In reselection, only conflicted players can select
                if user_id not in draft.conflicted_servants:
                    errors.append("Player is not in conflict and cannot reselect")
        
        return errors
    
    def validate_team_assignment(
        self, 
        draft: Draft, 
        captain_id: int, 
        player_id: int
    ) -> List[str]:
        """Validate team player assignment - preserves existing validation logic"""
        errors = []
        
        if draft.phase != DraftPhase.TEAM_SELECTION:
            errors.append("Not in team selection phase")
        
        if not draft.is_captain(captain_id):
            errors.append("Only captains can assign players to teams")
        
        if player_id not in draft.players:
            errors.append("Player is not in the draft")
        
        player = draft.get_player(player_id)
        if player and player.is_assigned_to_team:
            errors.append("Player is already assigned to a team")
        
        # Check if it's this captain's turn to pick
        if draft.current_picking_captain != captain_id:
            errors.append("It's not your turn to pick")
        
        # Check if captain's team is full
        captain_team_num = draft.get_captain_team(captain_id)
        if captain_team_num:
            team = draft.teams.get_team_by_number(captain_team_num)
            if team.is_full:
                errors.append("Your team is already full")
        
        return errors
    
    def validate_phase_transition(
        self, 
        draft: Draft, 
        target_phase: DraftPhase
    ) -> List[str]:
        """Validate phase transition - preserves existing transition logic"""
        errors = []
        
        if not draft.phase.can_transition_to(target_phase):
            errors.append(f"Cannot transition from {draft.phase.value} to {target_phase.value}")
        
        # Phase-specific validation
        if target_phase == DraftPhase.CAPTAIN_VOTING:
            if not draft.can_start:
                errors.append("Not enough players to start captain voting")
        
        elif target_phase == DraftPhase.SERVANT_BAN:
            if len(draft.captains) != 2:
                errors.append("Must have 2 captains before servant ban phase")
        
        elif target_phase == DraftPhase.SERVANT_SELECTION:
            if not all(draft.captain_ban_progress.get(cid, False) for cid in draft.captains):
                errors.append("All captains must complete banning before servant selection")
        
        elif target_phase == DraftPhase.TEAM_SELECTION:
            if not all(draft.selection_progress.get(uid, False) for uid in draft.players.keys()):
                # Check if we have conflicts that need reselection
                if len(draft.conflicted_servants) > 0:
                    errors.append("Servant conflicts must be resolved before team selection")
                else:
                    errors.append("All players must complete servant selection")
        
        elif target_phase == DraftPhase.COMPLETED:
            if not draft.teams.is_complete:
                errors.append("Teams must be complete before finishing draft")
        
        return errors
    
    def validate_draft_state(self, draft: Draft) -> List[str]:
        """Comprehensive draft state validation - preserves existing validation"""
        errors = []
        
        # Basic draft validation
        basic_errors = self._validate_basic_draft_structure(draft)
        errors.extend(basic_errors)
        
        # Phase-specific validation
        phase_errors = self._validate_phase_specific_state(draft)
        errors.extend(phase_errors)
        
        # Team validation
        team_errors = self._validate_team_structure(draft)
        errors.extend(team_errors)
        
        # Servant validation
        servant_errors = self._validate_servant_state(draft)
        errors.extend(servant_errors)
        
        return errors
    
    def _validate_basic_draft_structure(self, draft: Draft) -> List[str]:
        """Validate basic draft structure"""
        errors = []
        
        if draft.team_size < 1:
            errors.append("Team size must be positive")
        
        if len(draft.players) > draft.total_players_needed:
            errors.append("Too many players in draft")
        
        if draft.channel_id <= 0:
            errors.append("Invalid channel ID")
        
        if draft.guild_id <= 0:
            errors.append("Invalid guild ID")
        
        return errors
    
    def _validate_phase_specific_state(self, draft: Draft) -> List[str]:
        """Validate phase-specific state"""
        errors = []
        
        if draft.phase == DraftPhase.CAPTAIN_VOTING:
            if len(draft.captains) > 2:
                errors.append("Too many captains selected")
        
        elif draft.phase == DraftPhase.SERVANT_BAN:
            if len(draft.captains) != 2:
                errors.append("Must have exactly 2 captains for servant ban phase")
        
        elif draft.phase == DraftPhase.TEAM_SELECTION:
            if not draft.teams.both_have_captains:
                errors.append("Both teams must have captains for team selection")
            
            if draft.current_picking_captain and draft.current_picking_captain not in draft.captains:
                errors.append("Current picking captain is not valid")
        
        elif draft.phase == DraftPhase.COMPLETED:
            if not draft.teams.is_complete:
                errors.append("Teams are not complete")
        
        return errors
    
    def _validate_team_structure(self, draft: Draft) -> List[str]:
        """Validate team structure"""
        errors = []
        
        # Check team sizes match configuration
        if draft.teams.team1.max_size != draft.team_size:
            errors.append("Team 1 max size doesn't match draft team size")
        
        if draft.teams.team2.max_size != draft.team_size:
            errors.append("Team 2 max size doesn't match draft team size")
        
        # Check for player assignment conflicts
        team1_players = set(draft.teams.team1.player_ids)
        team2_players = set(draft.teams.team2.player_ids)
        
        overlap = team1_players & team2_players
        if overlap:
            errors.append(f"Players assigned to both teams: {overlap}")
        
        # Validate all assigned players exist in draft
        all_assigned = team1_players | team2_players
        for player_id in all_assigned:
            if player_id not in draft.players:
                errors.append(f"Assigned player {player_id} not in draft")
        
        return errors
    
    def _validate_servant_state(self, draft: Draft) -> List[str]:
        """Validate servant-related state"""
        errors = []
        
        # Check banned servants are actually in available set
        for banned_servant in draft.banned_servants:
            if banned_servant not in draft.available_servants:
                errors.append(f"Banned servant {banned_servant} is not in available servants")
        
        # Check selected servants
        selected_servants = {}
        for player in draft.players.values():
            if player.selected_servant:
                if player.selected_servant in selected_servants:
                    other_player = selected_servants[player.selected_servant]
                    errors.append(f"Servant {player.selected_servant} selected by both {player.username} and {other_player}")
                else:
                    selected_servants[player.selected_servant] = player.username
                
                # Check if selected servant is banned
                if player.selected_servant in draft.banned_servants:
                    errors.append(f"Player {player.username} selected banned servant {player.selected_servant}")
                
                # Check if selected servant is available
                if player.selected_servant not in draft.available_servants:
                    errors.append(f"Player {player.username} selected unavailable servant {player.selected_servant}")
        
        return errors
    
    def get_validation_summary(self, draft: Draft) -> Dict[str, any]:
        """Get comprehensive validation summary"""
        errors = self.validate_draft_state(draft)
        
        return {
            "is_valid": len(errors) == 0,
            "error_count": len(errors),
            "errors": errors,
            "phase": draft.phase.value,
            "can_advance": len(errors) == 0 and draft.phase != DraftPhase.COMPLETED
        }
