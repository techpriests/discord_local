"""
Player Entity

Represents a player participating in the draft.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Player:
    """Represents a player in the draft"""
    user_id: int
    username: str
    selected_servant: Optional[str] = None
    team: Optional[int] = None  # 1 or 2
    is_captain: bool = False
    
    def __post_init__(self):
        """Validate player data after initialization"""
        if self.team is not None and self.team not in [1, 2]:
            raise ValueError("Team must be 1 or 2")
    
    @property
    def is_assigned_to_team(self) -> bool:
        """Check if player is assigned to a team"""
        return self.team is not None
    
    @property
    def has_selected_servant(self) -> bool:
        """Check if player has selected a servant"""
        return self.selected_servant is not None
    
    def assign_to_team(self, team_number: int) -> None:
        """Assign player to a team"""
        if team_number not in [1, 2]:
            raise ValueError("Team must be 1 or 2")
        self.team = team_number
    
    def make_captain(self) -> None:
        """Make this player a captain"""
        self.is_captain = True
    
    def select_servant(self, servant_name: str) -> None:
        """Select a servant for this player"""
        if not servant_name:
            raise ValueError("Servant name cannot be empty")
        self.selected_servant = servant_name
    
    def clear_servant_selection(self) -> None:
        """Clear the servant selection"""
        self.selected_servant = None
    
    def reset_team_assignment(self) -> None:
        """Remove team assignment"""
        self.team = None
        self.is_captain = False
