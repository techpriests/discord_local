"""
Draft Phase Value Object

Represents the different phases of a draft with transition logic.
"""

from enum import Enum
from typing import List, Optional


class DraftPhase(Enum):
    """Phases of the draft system"""
    WAITING = "waiting"
    CAPTAIN_VOTING = "captain_voting"
    SERVANT_BAN = "servant_ban"
    SERVANT_SELECTION = "servant_selection"
    SERVANT_RESELECTION = "servant_reselection"
    TEAM_SELECTION = "team_selection"
    COMPLETED = "completed"

    @property
    def next_phases(self) -> List["DraftPhase"]:
        """Get valid next phases from current phase"""
        transitions = {
            self.WAITING: [self.CAPTAIN_VOTING],
            self.CAPTAIN_VOTING: [self.SERVANT_BAN],
            self.SERVANT_BAN: [self.SERVANT_SELECTION],
            self.SERVANT_SELECTION: [self.SERVANT_RESELECTION, self.TEAM_SELECTION],
            self.SERVANT_RESELECTION: [self.TEAM_SELECTION],
            self.TEAM_SELECTION: [self.COMPLETED],
            self.COMPLETED: []
        }
        return transitions.get(self, [])
    
    def can_transition_to(self, target_phase: "DraftPhase") -> bool:
        """Check if can transition to target phase"""
        return target_phase in self.next_phases
    
    @property
    def is_active(self) -> bool:
        """Check if this phase represents an active draft"""
        return self not in [self.WAITING, self.COMPLETED]
    
    @property
    def requires_user_input(self) -> bool:
        """Check if this phase requires user interaction"""
        return self in [
            self.CAPTAIN_VOTING,
            self.SERVANT_BAN,
            self.SERVANT_SELECTION,
            self.SERVANT_RESELECTION,
            self.TEAM_SELECTION
        ]
