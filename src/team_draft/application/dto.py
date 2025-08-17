"""
Data Transfer Objects

Simple data containers for transferring data between layers.
These preserve the exact information needed for UI while hiding internal domain complexity.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any
from ..domain.entities.draft_phase import DraftPhase


@dataclass
class PlayerDTO:
    """Player data for UI display"""
    user_id: int
    username: str
    selected_servant: Optional[str] = None
    team: Optional[int] = None
    is_captain: bool = False
    
    @classmethod
    def from_domain(cls, player) -> "PlayerDTO":
        """Convert from domain Player entity"""
        return cls(
            user_id=player.user_id,
            username=player.username,
            selected_servant=player.selected_servant,
            team=player.team,
            is_captain=player.is_captain
        )


@dataclass
class TeamDTO:
    """Team data for UI display"""
    team_number: int
    captain_id: Optional[int]
    player_ids: List[int]
    max_size: int
    
    @property
    def is_full(self) -> bool:
        return len(self.player_ids) >= self.max_size
    
    @property
    def player_count(self) -> int:
        return len(self.player_ids)


@dataclass
class DraftDTO:
    """Complete draft data for UI display"""
    # Core identification
    channel_id: int
    guild_id: int
    draft_id: str
    
    # Basic state
    team_size: int
    phase: str  # DraftPhase.value
    total_players_needed: int
    current_player_count: int
    
    # Players and teams
    players: List[PlayerDTO]
    team1: TeamDTO
    team2: TeamDTO
    
    # Captain information
    captains: List[int]
    captain_voting_progress: Dict[int, int]
    # captain_voting_time_remaining: Optional[int]  # Removed - legacy doesn't show real-time countdown
    
    # Servant information
    servant_categories: Dict[str, List[str]]
    detection_servants: List[str]
    cloaking_servants: List[str]
    
    # Selection progress
    selection_progress: Dict[int, bool]
    # selection_time_remaining: Optional[int]  # Removed - legacy doesn't show real-time countdown
    
    # Team selection
    current_picking_captain: Optional[int]
    team_selection_round: int
    first_pick_captain: Optional[int]
    
    # Metadata
    is_test_mode: bool
    is_simulation: bool
    started_by_user_id: Optional[int]
    thread_id: Optional[int]
    thread_name: Optional[str]
    
    # Servant system state
    servant_tiers: Dict[str, List[str]]
    banned_servants: Set[str]
    available_servants: Set[str]
    system_bans: List[str]
    captain_bans: Dict[int, List[str]]
    reselection_auto_bans: List[str]
    
    # Servant selection state
    conflicted_servants: Dict[str, List[int]]
    confirmed_servants: Dict[int, str]
    
    # Captain ban state
    captain_ban_dice_rolls: Dict[int, int]
    captain_ban_order: List[int]
    current_banning_captain: Optional[int]
    captain_ban_progress: Dict[int, bool]
    ban_progress_message_id: Optional[int]
    
    # Join lobby state
    join_target_total_players: Optional[int]
    join_user_ids: List[int]
    join_message_id: Optional[int]
    
    # Status flags
    can_start: bool
    is_full: bool
    is_active: bool
    is_completed: bool
    
    @classmethod
    def from_domain(cls, draft) -> "DraftDTO":
        """Convert from domain Draft entity"""
        # Convert players
        players = [PlayerDTO.from_domain(player) for player in draft.players.values()]
        
        # Convert teams
        team1 = TeamDTO(
            team_number=1,
            captain_id=draft.teams.team1.captain_id,
            player_ids=list(draft.teams.team1.player_ids),
            max_size=draft.teams.team1.max_size
        )
        
        team2 = TeamDTO(
            team_number=2,
            captain_id=draft.teams.team2.captain_id,
            player_ids=list(draft.teams.team2.player_ids),
            max_size=draft.teams.team2.max_size
        )
        
        return cls(
            # Core identification
            channel_id=draft.channel_id,
            guild_id=draft.guild_id,
            draft_id=draft.draft_id,
            
            # Basic state
            team_size=draft.team_size,
            phase=draft.phase.value,
            total_players_needed=draft.total_players_needed,
            current_player_count=draft.current_player_count,
            
            # Players and teams
            players=players,
            team1=team1,
            team2=team2,
            
            # Captain information
            captains=draft.captains.copy(),
            captain_voting_progress=dict(draft.captain_voting_progress),
            # captain_voting_time_remaining=draft._get_captain_voting_time_remaining(),  # Removed
            
            # Servant information (legacy)
            servant_categories=dict(draft.servant_categories),
            detection_servants=list(draft.detection_servants),
            cloaking_servants=list(draft.cloaking_servants),
            
            # Selection progress
            selection_progress=dict(draft.selection_progress),
            # selection_time_remaining=draft._get_selection_time_remaining(),  # Removed
            
            # Team selection
            current_picking_captain=draft.current_picking_captain,
            team_selection_round=draft.team_selection_round,
            first_pick_captain=draft.first_pick_captain,
            
            # Metadata
            is_test_mode=draft.is_test_mode,
            is_simulation=draft.is_simulation,
            started_by_user_id=draft.started_by_user_id,
            thread_id=draft.thread_id,
            thread_name=draft.thread_name,
            
            # Servant system state
            servant_tiers=dict(draft.servant_tiers),
            banned_servants=set(draft.banned_servants),
            available_servants=set(draft.available_servants),
            system_bans=list(draft.system_bans),
            captain_bans=dict(draft.captain_bans),
            reselection_auto_bans=list(draft.reselection_auto_bans),
            
            # Servant selection state
            conflicted_servants=dict(draft.conflicted_servants),
            confirmed_servants=dict(draft.confirmed_servants),
            
            # Captain ban state
            captain_ban_dice_rolls=dict(draft.captain_ban_dice_rolls),
            captain_ban_order=list(draft.captain_ban_order),
            current_banning_captain=draft.current_banning_captain,
            captain_ban_progress=dict(draft.captain_ban_progress),
            ban_progress_message_id=draft.ban_progress_message_id,
            
            # Join lobby state
            join_target_total_players=draft.join_target_total_players,
            join_user_ids=list(draft.join_user_ids),
            join_message_id=draft.join_message_id,
            
            # Status flags
            can_start=draft.can_start,
            is_full=draft.is_full,
            is_active=draft.is_active,
            is_completed=draft.is_completed
        )


# Result DTOs for operation outcomes

@dataclass
class JoinResult:
    """Result of joining a draft"""
    success: bool
    message: Optional[str] = None
    should_update_embed: bool = False
    should_auto_start: bool = False
    error_code: Optional[str] = None


@dataclass
class VoteResult:
    """Result of captain voting"""
    success: bool
    message: Optional[str] = None
    votes_cast: int = 0
    vote_limit_reached: bool = False
    voting_completed: bool = False
    error_code: Optional[str] = None


@dataclass
class SelectionResult:
    """Result of servant selection"""
    success: bool
    message: Optional[str] = None
    servant_selected: Optional[str] = None
    selection_completed: bool = False
    should_advance_phase: bool = False
    error_code: Optional[str] = None


@dataclass
class TeamAssignmentResult:
    """Result of team player assignment"""
    success: bool
    message: Optional[str] = None
    player_assigned: Optional[int] = None
    team_number: Optional[int] = None
    assignment_completed: bool = False
    should_advance_phase: bool = False
    error_code: Optional[str] = None


@dataclass
class PhaseTransitionResult:
    """Result of phase transition"""
    success: bool
    message: Optional[str] = None
    old_phase: Optional[str] = None
    new_phase: Optional[str] = None
    should_update_ui: bool = False
    error_code: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validation check"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
