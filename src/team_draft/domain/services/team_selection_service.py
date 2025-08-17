"""
Team Selection Service

Handles team selection patterns and logic for different team sizes.
Preserves legacy team selection patterns and round-based selection logic.
"""

from typing import Dict, List, Optional, Any
from ..entities.draft import Draft
from ..exceptions import DraftError


class TeamSelectionService:
    """
    Service for managing team selection patterns and logic.
    
    Preserves legacy selection patterns:
    - 2v2: 1-1 pattern
    - 3v3: 1-2, 1-0 pattern  
    - 5v5: 1-2, 2-2, 1-0 pattern
    - 6v6: 1-2, 2-2, 2-1 pattern
    """
    
    def __init__(self):
        # Team selection patterns from legacy system
        self.team_selection_patterns = {
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
                {"first_pick": 1, "second_pick": 0},  # Round 3: First picks 1, Second picks 0
            ],
            6: [  # 6v6 pattern - corrected to 1-2-2 / 2-2-1 
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 2, "second_pick": 2},  # Round 2: First picks 2, Second picks 2  
                {"first_pick": 2, "second_pick": 1},  # Round 3: First picks 2, Second picks 1
            ]
        }
    
    def get_selection_pattern(self, team_size: int) -> List[Dict[str, int]]:
        """Get the selection pattern for a given team size"""
        if team_size not in self.team_selection_patterns:
            raise ValueError(f"No selection pattern defined for team size {team_size}")
        
        return self.team_selection_patterns[team_size]
    
    def get_round_info(self, team_size: int, round_number: int) -> Dict[str, int]:
        """
        Get selection info for a specific round
        
        Args:
            team_size: Size of each team
            round_number: Round number (1-based)
            
        Returns:
            Dict with "first_pick" and "second_pick" counts
        """
        pattern = self.get_selection_pattern(team_size)
        
        if round_number < 1 or round_number > len(pattern):
            raise ValueError(f"Invalid round {round_number} for team size {team_size}")
        
        return pattern[round_number - 1]
    
    def get_max_picks_for_captain(
        self, 
        team_size: int, 
        round_number: int, 
        is_first_pick_captain: bool
    ) -> int:
        """Get maximum picks allowed for a captain in a specific round"""
        round_info = self.get_round_info(team_size, round_number)
        
        if is_first_pick_captain:
            return round_info["first_pick"]
        else:
            return round_info["second_pick"]
    
    def initialize_team_selection(self, draft: Draft) -> None:
        """Initialize team selection state for a draft"""
        # Initialize selection tracking
        draft.team_selection_round = 1
        draft.picks_this_round = {captain: 0 for captain in draft.captains}
        draft.team_selection_progress = {}
        draft.pending_team_selections = {}
        
        # Set first picking captain (usually determined by some other logic)
        if draft.captains and not draft.first_pick_captain:
            draft.first_pick_captain = draft.captains[0]
        
        # Set current picking captain to first pick captain
        draft.current_picking_captain = draft.first_pick_captain
    
    def can_captain_pick(
        self, 
        draft: Draft, 
        captain_id: int
    ) -> bool:
        """Check if a captain can make picks in the current round"""
        if captain_id != draft.current_picking_captain:
            return False
        
        # Check if captain already completed this round
        current_round = draft.team_selection_round
        if (captain_id in draft.team_selection_progress and 
            current_round in draft.team_selection_progress[captain_id] and
            draft.team_selection_progress[captain_id][current_round]):
            return False
        
        return True
    
    def get_available_picks_count(
        self, 
        draft: Draft, 
        captain_id: int
    ) -> int:
        """Get how many more picks a captain can make this round"""
        if not self.can_captain_pick(draft, captain_id):
            return 0
        
        is_first_pick = captain_id == draft.first_pick_captain
        max_picks = self.get_max_picks_for_captain(
            draft.team_size, 
            draft.team_selection_round, 
            is_first_pick
        )
        
        # Count pending selections
        current_pending = len(draft.pending_team_selections.get(captain_id, []))
        
        return max_picks - current_pending
    
    def advance_team_selection(self, draft: Draft) -> bool:
        """
        Advance team selection to next captain or round
        
        Returns:
            True if selection continues, False if completed
        """
        current_captain = draft.current_picking_captain
        current_round = draft.team_selection_round
        
        # Get round info
        round_info = self.get_round_info(draft.team_size, current_round)
        
        # Check if current captain finished their picks
        picks_made = draft.picks_this_round.get(current_captain, 0)
        is_first_pick = current_captain == draft.first_pick_captain
        max_picks = round_info["first_pick"] if is_first_pick else round_info["second_pick"]
        
        if picks_made >= max_picks:
            # Switch to other captain or next round
            other_captain = [c for c in draft.captains if c != current_captain][0]
            other_picks = draft.picks_this_round.get(other_captain, 0)
            other_max = round_info["second_pick"] if is_first_pick else round_info["first_pick"]
            
            if other_picks < other_max:
                # Switch to other captain
                draft.current_picking_captain = other_captain
            else:
                # Move to next round
                draft.team_selection_round += 1
                draft.picks_this_round = {captain: 0 for captain in draft.captains}
                
                # Check if we have more rounds
                pattern = self.get_selection_pattern(draft.team_size)
                if draft.team_selection_round > len(pattern):
                    # Team selection completed
                    return False
                
                # Determine who picks first in new round (usually alternates or follows pattern)
                draft.current_picking_captain = draft.first_pick_captain
        
        return True
    
    def is_team_selection_complete(self, draft: Draft) -> bool:
        """Check if team selection is complete"""
        pattern = self.get_selection_pattern(draft.team_size)
        return draft.team_selection_round > len(pattern)
    
    def get_unassigned_players(self, draft: Draft) -> List[int]:
        """Get list of player IDs who haven't been assigned to teams yet"""
        unassigned = []
        
        # Get all pending selections to exclude them
        all_pending = set()
        for pending_list in draft.pending_team_selections.values():
            all_pending.update(pending_list)
        
        for player_id, player in draft.players.items():
            if (player.team is None and 
                not player.is_captain and 
                player_id not in all_pending):
                unassigned.append(player_id)
        
        return unassigned
