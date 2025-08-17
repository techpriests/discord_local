"""
Team Service - Domain Service

Handles team composition, selection patterns, and team assignment logic.
Preserves all existing team selection algorithms and patterns.
"""

from typing import Dict, List, Optional, Tuple
from ..entities.draft import Draft
from ..entities.draft_phase import DraftPhase
from ..entities.player import Player
from ..exceptions import (
    InvalidDraftStateError,
    TeamSelectionError,
    InvalidCaptainError,
    TeamFullError,
    PlayerNotFoundError
)


class TeamService:
    """
    Domain service for team-related operations.
    
    Preserves all existing team selection patterns and logic.
    """
    
    # Team selection patterns - preserves existing patterns from original code
    TEAM_SELECTION_PATTERNS = {
        2: [  # 2v2 pattern
            {"first_pick": 1, "second_pick": 1},  # Round 1: Each captain picks 1
        ],
        3: [  # 3v3 pattern
            {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
            {"first_pick": 1, "second_pick": 0},  # Round 2: First picks 1, Second picks 0
        ],
        5: [  # 5v5 pattern
            {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
            {"first_pick": 2, "second_pick": 2},  # Round 2: Each picks 2
        ],
        6: [  # 6v6 pattern
            {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
            {"first_pick": 2, "second_pick": 2},  # Round 2: Each picks 2
            {"first_pick": 1, "second_pick": 0},  # Round 3: First picks 1, Second picks 0
        ]
    }
    
    def get_selection_pattern(self, team_size: int) -> List[Dict[str, int]]:
        """Get team selection pattern for given team size - preserves existing patterns"""
        return self.TEAM_SELECTION_PATTERNS.get(team_size, [])
    
    def get_current_round_pattern(self, draft: Draft) -> Optional[Dict[str, int]]:
        """Get current round selection pattern"""
        pattern = self.get_selection_pattern(draft.team_size)
        if not pattern or draft.team_selection_round > len(pattern):
            return None
        
        return pattern[draft.team_selection_round - 1]
    
    def get_picks_needed_for_captain(self, draft: Draft, captain_id: int) -> int:
        """Get number of picks needed for captain in current round"""
        if not draft.is_captain(captain_id):
            return 0
        
        pattern = self.get_current_round_pattern(draft)
        if not pattern:
            return 0
        
        # Determine if this captain picks first or second
        is_first_pick = captain_id == draft.first_pick_captain
        picks_key = "first_pick" if is_first_pick else "second_pick"
        
        total_picks_needed = pattern[picks_key]
        picks_made = draft.picks_this_round.get(captain_id, 0)
        
        return max(0, total_picks_needed - picks_made)
    
    def can_captain_pick(self, draft: Draft, captain_id: int) -> bool:
        """Check if captain can pick in current round - preserves existing logic"""
        if draft.phase != DraftPhase.TEAM_SELECTION:
            return False
        
        if not draft.is_captain(captain_id):
            return False
        
        # Check if it's this captain's turn
        if draft.current_picking_captain != captain_id:
            return False
        
        # Check if captain still needs to pick
        return self.get_picks_needed_for_captain(draft, captain_id) > 0
    
    def get_available_players_for_selection(self, draft: Draft) -> List[Player]:
        """Get players available for team selection"""
        return draft.get_unassigned_players()
    
    def assign_player_to_captain_team(
        self, 
        draft: Draft, 
        captain_id: int, 
        player_id: int
    ) -> Tuple[bool, str]:
        """
        Assign player to captain's team - preserves existing assignment logic
        
        Returns:
            Tuple of (success, message)
        """
        if not self.can_captain_pick(draft, captain_id):
            return False, "You cannot pick players at this time"
        
        player = draft.get_player(player_id)
        if not player:
            return False, f"Player {player_id} not found"
        
        if player.is_assigned_to_team:
            return False, f"{player.username} is already on a team"
        
        # Get captain's team number
        captain_team = draft.get_captain_team(captain_id)
        if captain_team is None:
            return False, "Captain team not found"
        
        try:
            # Assign player to team
            draft.assign_player_to_team(captain_id, player_id, captain_team)
            
            # Update pick tracking
            draft.picks_this_round[captain_id] = draft.picks_this_round.get(captain_id, 0) + 1
            
            return True, f"Assigned {player.username} to team {captain_team}"
            
        except Exception as e:
            return False, str(e)
    
    def advance_picking_turn(self, draft: Draft) -> Optional[int]:
        """
        Advance to next captain's turn - preserves existing turn logic
        
        Returns:
            Next captain ID or None if round is complete
        """
        if draft.phase != DraftPhase.TEAM_SELECTION:
            return None
        
        current_captain = draft.current_picking_captain
        if not current_captain:
            return None
        
        # Check if current captain has completed their picks for this round
        picks_needed = self.get_picks_needed_for_captain(draft, current_captain)
        if picks_needed > 0:
            # Captain still needs to pick
            return current_captain
        
        # Current captain is done, switch to other captain
        other_captain = None
        for captain_id in draft.captains:
            if captain_id != current_captain:
                other_captain = captain_id
                break
        
        if other_captain:
            picks_needed_other = self.get_picks_needed_for_captain(draft, other_captain)
            if picks_needed_other > 0:
                # Other captain needs to pick
                draft.current_picking_captain = other_captain
                return other_captain
        
        # Both captains are done with this round
        return self.advance_to_next_round(draft)
    
    def advance_to_next_round(self, draft: Draft) -> Optional[int]:
        """
        Advance to next selection round - preserves existing round logic
        
        Returns:
            Next captain ID or None if selection is complete
        """
        if draft.phase != DraftPhase.TEAM_SELECTION:
            return None
        
        pattern = self.get_selection_pattern(draft.team_size)
        if draft.team_selection_round >= len(pattern):
            # All rounds complete
            return None
        
        # Move to next round
        draft.team_selection_round += 1
        
        # Reset picks for new round
        for captain_id in draft.captains:
            draft.picks_this_round[captain_id] = 0
            draft.team_selection_progress[captain_id][draft.team_selection_round] = False
        
        # Determine who picks first in new round (alternates)
        current_pattern = self.get_current_round_pattern(draft)
        if not current_pattern:
            return None
        
        # First pick captain starts the new round
        draft.current_picking_captain = draft.first_pick_captain
        return draft.first_pick_captain
    
    def is_team_selection_complete(self, draft: Draft) -> bool:
        """Check if team selection is complete - preserves existing completion logic"""
        if draft.phase != DraftPhase.TEAM_SELECTION:
            return False
        
        # Check if all players are assigned
        unassigned = self.get_available_players_for_selection(draft)
        if len(unassigned) > 0:
            return False
        
        # Check if teams are full
        return draft.teams.is_complete
    
    def get_team_selection_status(self, draft: Draft) -> Dict[str, any]:
        """Get current team selection status - preserves existing status tracking"""
        if draft.phase != DraftPhase.TEAM_SELECTION:
            return {"phase": "not_selecting"}
        
        status = {
            "phase": "team_selection",
            "current_round": draft.team_selection_round,
            "current_picking_captain": draft.current_picking_captain,
            "first_pick_captain": draft.first_pick_captain,
            "picks_this_round": dict(draft.picks_this_round),
            "team_selection_progress": {
                k: dict(v) for k, v in draft.team_selection_progress.items()
            },
            "available_players": [
                {"user_id": p.user_id, "username": p.username} 
                for p in self.get_available_players_for_selection(draft)
            ],
            "team1_players": list(draft.teams.team1.player_ids),
            "team2_players": list(draft.teams.team2.player_ids),
            "is_complete": self.is_team_selection_complete(draft)
        }
        
        # Add current round pattern info
        pattern = self.get_current_round_pattern(draft)
        if pattern:
            status["current_pattern"] = pattern
            
            # Add picks needed for each captain
            for captain_id in draft.captains:
                picks_needed = self.get_picks_needed_for_captain(draft, captain_id)
                can_pick = self.can_captain_pick(draft, captain_id)
                status[f"captain_{captain_id}_picks_needed"] = picks_needed
                status[f"captain_{captain_id}_can_pick"] = can_pick
        
        return status
    
    def validate_team_composition(self, draft: Draft) -> List[str]:
        """Validate team composition - preserves existing validation logic"""
        issues = []
        
        # Check team sizes
        if draft.teams.team1.player_count != draft.team_size:
            issues.append(f"Team 1 has {draft.teams.team1.player_count} players, expected {draft.team_size}")
        
        if draft.teams.team2.player_count != draft.team_size:
            issues.append(f"Team 2 has {draft.teams.team2.player_count} players, expected {draft.team_size}")
        
        # Check all players are assigned
        total_assigned = draft.teams.team1.player_count + draft.teams.team2.player_count
        if total_assigned != len(draft.players):
            issues.append(f"Not all players are assigned to teams ({total_assigned}/{len(draft.players)})")
        
        # Check captains are on different teams
        if draft.teams.both_have_captains:
            if draft.teams.team1.captain_id == draft.teams.team2.captain_id:
                issues.append("Both teams have the same captain")
        else:
            issues.append("Not all teams have captains")
        
        # Check for duplicate assignments
        all_assigned_players = set(draft.teams.team1.player_ids) | set(draft.teams.team2.player_ids)
        if len(all_assigned_players) != total_assigned:
            issues.append("Some players are assigned to multiple teams")
        
        return issues
    
    def get_team_balance_info(self, draft: Draft) -> Dict[str, any]:
        """Get team balance information for analysis"""
        balance_info = {
            "team_sizes": {
                "team1": draft.teams.team1.player_count,
                "team2": draft.teams.team2.player_count
            },
            "captains": {
                "team1": draft.teams.team1.captain_id,
                "team2": draft.teams.team2.captain_id
            },
            "servants_per_team": {
                "team1": {},
                "team2": {}
            },
            "special_abilities": {
                "team1": {"detection": 0, "cloaking": 0},
                "team2": {"detection": 0, "cloaking": 0}
            }
        }
        
        # Analyze servant distribution
        for player in draft.players.values():
            if player.team and player.selected_servant:
                team_key = f"team{player.team}"
                servant = player.selected_servant
                
                # Count servants by category
                for category, servants in draft.servant_categories.items():
                    if servant in servants:
                        if category not in balance_info["servants_per_team"][team_key]:
                            balance_info["servants_per_team"][team_key][category] = 0
                        balance_info["servants_per_team"][team_key][category] += 1
                
                # Count special abilities
                if servant in draft.detection_servants:
                    balance_info["special_abilities"][team_key]["detection"] += 1
                if servant in draft.cloaking_servants:
                    balance_info["special_abilities"][team_key]["cloaking"] += 1
        
        return balance_info
    
    def suggest_optimal_picks(self, draft: Draft, captain_id: int) -> List[Dict[str, any]]:
        """Suggest optimal picks for captain based on team composition"""
        if not self.can_captain_pick(draft, captain_id):
            return []
        
        available_players = self.get_available_players_for_selection(draft)
        suggestions = []
        
        # Get current team composition
        captain_team = draft.get_captain_team(captain_id)
        if not captain_team:
            return []
        
        team = draft.teams.get_team_by_number(captain_team)
        current_servants = []
        current_detection = 0
        current_cloaking = 0
        
        # Analyze current team composition
        for player_id in team.player_ids:
            player = draft.get_player(player_id)
            if player and player.selected_servant:
                current_servants.append(player.selected_servant)
                if player.selected_servant in draft.detection_servants:
                    current_detection += 1
                if player.selected_servant in draft.cloaking_servants:
                    current_cloaking += 1
        
        # Score available players
        for player in available_players:
            if not player.selected_servant:
                continue
            
            score = 0
            reasons = []
            
            # Bonus for detection servants if team lacks them
            if player.selected_servant in draft.detection_servants and current_detection == 0:
                score += 3
                reasons.append("Provides detection ability")
            
            # Bonus for cloaking servants if opponent has detection
            opposing_team_num = 2 if captain_team == 1 else 1
            opposing_team = draft.teams.get_team_by_number(opposing_team_num)
            opposing_detection = 0
            for opp_player_id in opposing_team.player_ids:
                opp_player = draft.get_player(opp_player_id)
                if opp_player and opp_player.selected_servant in draft.detection_servants:
                    opposing_detection += 1
            
            if player.selected_servant in draft.cloaking_servants and opposing_detection > 0:
                score += 2
                reasons.append("Counters enemy detection")
            
            # Category diversity bonus
            player_category = None
            for category, servants in draft.servant_categories.items():
                if player.selected_servant in servants:
                    player_category = category
                    break
            
            if player_category:
                category_count = sum(1 for s in current_servants 
                                   for cat, servs in draft.servant_categories.items() 
                                   if cat == player_category and s in servs)
                if category_count == 0:
                    score += 1
                    reasons.append(f"Adds {player_category} class diversity")
            
            suggestions.append({
                "player": {
                    "user_id": player.user_id,
                    "username": player.username,
                    "servant": player.selected_servant
                },
                "score": score,
                "reasons": reasons
            })
        
        # Sort by score (highest first)
        suggestions.sort(key=lambda x: x["score"], reverse=True)
        
        return suggestions[:5]  # Return top 5 suggestions
