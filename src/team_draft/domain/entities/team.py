"""
Team Entity

Represents a team in the draft with composition rules and validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from .player import Player


@dataclass
class Team:
    """Represents a team in the draft"""
    team_number: int  # 1 or 2
    captain_id: Optional[int] = None
    player_ids: Set[int] = field(default_factory=set)
    max_size: int = 6
    
    def __post_init__(self):
        """Validate team data"""
        if self.team_number not in [1, 2]:
            raise ValueError("Team number must be 1 or 2")
        if self.max_size < 1:
            raise ValueError("Max size must be positive")
    
    @property
    def is_full(self) -> bool:
        """Check if team is at maximum capacity"""
        return len(self.player_ids) >= self.max_size
    
    @property
    def has_captain(self) -> bool:
        """Check if team has a captain assigned"""
        return self.captain_id is not None
    
    @property
    def player_count(self) -> int:
        """Get current number of players"""
        return len(self.player_ids)
    
    @property
    def needs_players(self) -> int:
        """Get number of players still needed"""
        return max(0, self.max_size - len(self.player_ids))
    
    def can_add_player(self) -> bool:
        """Check if team can accept another player"""
        return not self.is_full
    
    def add_player(self, player_id: int) -> None:
        """Add a player to the team"""
        if self.is_full:
            raise ValueError(f"Team {self.team_number} is already full")
        if player_id in self.player_ids:
            raise ValueError(f"Player {player_id} is already on team {self.team_number}")
        self.player_ids.add(player_id)
    
    def remove_player(self, player_id: int) -> None:
        """Remove a player from the team"""
        if player_id not in self.player_ids:
            raise ValueError(f"Player {player_id} is not on team {self.team_number}")
        self.player_ids.discard(player_id)
        
        # If removing the captain, clear captain assignment
        if self.captain_id == player_id:
            self.captain_id = None
    
    def set_captain(self, captain_id: int) -> None:
        """Set the team captain"""
        if captain_id not in self.player_ids:
            raise ValueError(f"Captain {captain_id} must be a member of team {self.team_number}")
        self.captain_id = captain_id
    
    def clear_captain(self) -> None:
        """Remove captain assignment"""
        self.captain_id = None
    
    def contains_player(self, player_id: int) -> bool:
        """Check if player is on this team"""
        return player_id in self.player_ids


@dataclass
class TeamComposition:
    """Represents the overall team composition for a draft"""
    team1: Team = field(default_factory=lambda: Team(1))
    team2: Team = field(default_factory=lambda: Team(2))
    
    def __post_init__(self):
        """Ensure both teams have same max size"""
        if self.team1.max_size != self.team2.max_size:
            raise ValueError("Both teams must have the same max size")
    
    @property
    def team_size(self) -> int:
        """Get the size each team should reach"""
        return self.team1.max_size
    
    @property
    def total_players_needed(self) -> int:
        """Get total number of players needed for both teams"""
        return self.team1.max_size * 2
    
    @property
    def current_player_count(self) -> int:
        """Get current total number of players across both teams"""
        return self.team1.player_count + self.team2.player_count
    
    @property
    def is_complete(self) -> bool:
        """Check if both teams are full"""
        return self.team1.is_full and self.team2.is_full
    
    @property
    def both_have_captains(self) -> bool:
        """Check if both teams have captains"""
        return self.team1.has_captain and self.team2.has_captain
    
    def get_team_by_number(self, team_number: int) -> Team:
        """Get team by number"""
        if team_number == 1:
            return self.team1
        elif team_number == 2:
            return self.team2
        else:
            raise ValueError("Team number must be 1 or 2")
    
    def get_player_team(self, player_id: int) -> Optional[Team]:
        """Get the team a player belongs to"""
        if self.team1.contains_player(player_id):
            return self.team1
        elif self.team2.contains_player(player_id):
            return self.team2
        return None
    
    def get_captain_ids(self) -> List[int]:
        """Get list of captain IDs"""
        captains = []
        if self.team1.captain_id:
            captains.append(self.team1.captain_id)
        if self.team2.captain_id:
            captains.append(self.team2.captain_id)
        return captains
    
    def set_team_size(self, size: int) -> None:
        """Set the size for both teams"""
        if size < 1:
            raise ValueError("Team size must be positive")
        self.team1.max_size = size
        self.team2.max_size = size
