"""
Draft Entity - Aggregate Root

Main entity representing a complete draft session with all its state and behavior.
This preserves all the functionality from the original DraftSession while adding
proper domain methods and validation.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any

from .draft_phase import DraftPhase
from .player import Player
from .team import TeamComposition


@dataclass
class Draft:
    """
    Draft aggregate root - manages the complete lifecycle of a team draft.
    
    This class preserves all the existing functionality from DraftSession
    while adding proper domain methods and validation.
    """
    
    # Core identification
    channel_id: int
    guild_id: int
    draft_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Basic configuration
    team_size: int = 6  # Number of players per team (2 for 2v2, 3 for 3v3, 5 for 5v5, 6 for 6v6)
    phase: DraftPhase = DraftPhase.WAITING
    
    # Players and teams
    players: Dict[int, Player] = field(default_factory=dict)
    teams: TeamComposition = field(default_factory=TeamComposition)
    
    # Draft metadata
    started_by_user_id: Optional[int] = None
    thread_id: Optional[int] = None  # Thread where draft takes place
    match_id: Optional[str] = None
    
    # Test and simulation mode
    is_test_mode: bool = False
    real_user_id: Optional[int] = None  # The real user in test mode
    is_simulation: bool = False
    simulation_session_id: Optional[str] = None
    simulation_author_id: Optional[int] = None
    
    # Captain selection and voting
    captain_vote_message_id: Optional[int] = None
    captains: List[int] = field(default_factory=list)  # user_ids
    captain_voting_progress: Dict[int, int] = field(default_factory=dict)  # user_id -> number of votes cast
    captain_voting_progress_message_id: Optional[int] = None
    captain_voting_start_time: Optional[float] = None
    captain_voting_time_limit: int = 120  # 2 minutes in seconds
    
    # Servant system - tier definitions for ban system
    servant_tiers: Dict[str, List[str]] = field(default_factory=lambda: {
        "S": ["헤클", "길가", "란슬", "가재"],  # '란슬' moved to S, '네로' moved to A
        "A": ["세이버", "네로", "카르나", "룰러"],  # '네로' moved to A, '란슬' moved to S
        "B": ["디미", "이칸", "산노", "서문", "바토리"]
    })
    
    # Servant selection - organized by categories
    servant_categories: Dict[str, List[str]] = field(default_factory=lambda: {
        "세이버": ["세이버", "흑화 세이버", "가웨인", "네로", "모드레드", "무사시", "지크"],
        "랜서": ["쿠훌린", "디미", "가재", "카르나", "바토리"],
        "아처": ["아처", "길가", "아엑", "아탈"],
        "라이더": ["메두사", "이칸", "라엑", "톨포"],
        "캐스터": ["메데이아", "질드레", "타마", "너서리", "셰익", "안데"],
        "어새신": ["허새", "징어", "서문", "잭더리퍼", "세미", "산노", "시키"],
        "버서커": ["헤클", "란슬", "여포", "프랑"],
        "엑스트라": ["어벤저", "룰러", "멜트", "암굴"]
    })
    
    available_servants: Set[str] = field(default_factory=lambda: {
        # Flatten all categories into a single set
        "세이버", "흑화 세이버", "가웨인", "네로", "모드레드", "무사시", "지크",
        "쿠훌린", "디미", "가재", "카르나", "바토리",
        "아처", "길가", "아엑", "아탈",
        "메두사", "이칸", "라엑", "톨포",
        "메데이아", "질드레", "타마", "너서리", "셰익", "안데",
        "허새", "징어", "서문", "잭더리퍼", "세미", "산노", "시키",
        "헤클", "란슬", "여포", "프랑",
        "어벤저", "룰러", "멜트", "암굴"
    })
    
    # Special ability servants
    detection_servants: Set[str] = field(default_factory=lambda: {
        "아처", "룰러", "너서리", "아탈", "가웨인", "디미", "허새"
    })
    cloaking_servants: Set[str] = field(default_factory=lambda: {
        "서문", "징어", "잭더리퍼", "세미", "안데"
    })
    conflicted_servants: Dict[str, List[int]] = field(default_factory=dict)
    confirmed_servants: Dict[int, str] = field(default_factory=dict)
    
    # Team selection with confirmation support
    first_pick_captain: Optional[int] = None
    team_selection_round: int = 1
    current_picking_captain: Optional[int] = None
    picks_this_round: Dict[int, int] = field(default_factory=dict)  # captain_id -> picks_made
    pending_team_selections: Dict[int, List[int]] = field(default_factory=dict)  # captain_id -> [pending_user_ids]
    team_selection_progress: Dict[int, Dict[int, bool]] = field(default_factory=dict)  # captain_id -> {round -> completed}
    
    # Servant ban phase - enhanced for new system
    banned_servants: Set[str] = field(default_factory=set)
    system_bans: List[str] = field(default_factory=list)  # System's automated bans
    captain_bans: Dict[int, List[str]] = field(default_factory=dict)  # captain_id -> banned_servants
    captain_ban_progress: Dict[int, bool] = field(default_factory=dict)  # captain_id -> completed
    captain_ban_order: List[int] = field(default_factory=list)  # Order of captain bans determined by dice
    current_banning_captain: Optional[int] = None  # Which captain is currently banning
    
    # Servant selection progress tracking
    selection_progress: Dict[int, bool] = field(default_factory=dict)  # user_id -> completed
    reselection_round: int = 0  # Track reselection rounds to prevent infinite loops
    
    # Time limits for various phases
    selection_start_time: Optional[float] = None
    selection_time_limit: int = 90  # 1 minute 30 seconds
    reselection_start_time: Optional[float] = None
    reselection_time_limit: int = 90  # 1 minute 30 seconds
    
    # Task tracking for proper cleanup
    running_tasks: Set = field(default_factory=set)
    
    # Messages for state tracking - UI concerns but needed for state preservation
    status_message_id: Optional[int] = None
    ban_progress_message_id: Optional[int] = None
    selection_progress_message_id: Optional[int] = None
    selection_buttons_message_id: Optional[int] = None
    last_progress_update_hash: Optional[str] = field(default=None)
    last_voting_progress_hash: Optional[str] = field(default=None)
    
    # Join-based start support
    join_target_total_players: Optional[int] = None
    join_user_ids: Set[int] = field(default_factory=set)
    join_message_id: Optional[int] = None
    
    # Finish/outcome handling
    finish_view_message_id: Optional[int] = None
    outcome_recorded: bool = False
    auto_balance_result: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Initialize teams with correct size"""
        self.teams.set_team_size(self.team_size)
    
    # ===================
    # Core Draft Methods
    # ===================
    
    @property
    def total_players_needed(self) -> int:
        """Total number of players needed for the draft"""
        return self.team_size * 2
    
    @property
    def current_player_count(self) -> int:
        """Current number of players in the draft"""
        return len(self.players)
    
    @property
    def is_full(self) -> bool:
        """Check if draft has enough players"""
        return self.current_player_count >= self.total_players_needed
    
    @property
    def can_start(self) -> bool:
        """Check if draft can start (has enough players)"""
        return self.is_full and self.phase == DraftPhase.WAITING
    
    @property
    def is_active(self) -> bool:
        """Check if draft is currently active"""
        return self.phase.is_active
    
    @property
    def is_completed(self) -> bool:
        """Check if draft is completed"""
        return self.phase == DraftPhase.COMPLETED
    
    def add_player(self, user_id: int, username: str) -> None:
        """Add a player to the draft"""
        if self.is_full:
            raise ValueError("Draft is already full")
        if user_id in self.players:
            raise ValueError(f"Player {user_id} is already in the draft")
        
        self.players[user_id] = Player(user_id=user_id, username=username)
        if self.join_target_total_players:
            self.join_user_ids.add(user_id)
    
    def remove_player(self, user_id: int) -> None:
        """Remove a player from the draft"""
        if user_id not in self.players:
            raise ValueError(f"Player {user_id} is not in the draft")
        
        # Remove from any team assignment
        player = self.players[user_id]
        if player.team:
            team = self.teams.get_team_by_number(player.team)
            team.remove_player(user_id)
        
        # Remove from captain list if captain
        if user_id in self.captains:
            self.captains.remove(user_id)
        
        # Remove from players
        del self.players[user_id]
        self.join_user_ids.discard(user_id)
    
    def get_player(self, user_id: int) -> Optional[Player]:
        """Get a player by user ID"""
        return self.players.get(user_id)
    
    def advance_phase(self, target_phase: DraftPhase) -> None:
        """Advance to the next phase with validation"""
        if not self.phase.can_transition_to(target_phase):
            raise ValueError(f"Cannot transition from {self.phase.value} to {target_phase.value}")
        self.phase = target_phase
    
    # ===================
    # Captain Methods
    # ===================
    
    def set_captains(self, captain_ids: List[int]) -> None:
        """Set the draft captains"""
        if len(captain_ids) != 2:
            raise ValueError("Must have exactly 2 captains")
        
        for captain_id in captain_ids:
            if captain_id not in self.players:
                raise ValueError(f"Captain {captain_id} is not in the draft")
        
        self.captains = captain_ids.copy()
        
        # Assign captains to teams and mark as captains
        for i, captain_id in enumerate(captain_ids):
            team_number = i + 1
            player = self.players[captain_id]
            player.make_captain()
            player.assign_to_team(team_number)
            
            team = self.teams.get_team_by_number(team_number)
            team.add_player(captain_id)
            team.set_captain(captain_id)
    
    def is_captain(self, user_id: int) -> bool:
        """Check if user is a captain"""
        return user_id in self.captains
    
    def get_captain_team(self, captain_id: int) -> Optional[int]:
        """Get the team number for a captain"""
        if not self.is_captain(captain_id):
            return None
        player = self.get_player(captain_id)
        return player.team if player else None
    
    # ===================
    # Servant Methods
    # ===================
    
    def ban_servant(self, servant_name: str, banned_by: Optional[int] = None) -> None:
        """Ban a servant from selection"""
        if servant_name not in self.available_servants:
            raise ValueError(f"Servant {servant_name} is not available")
        if servant_name in self.banned_servants:
            raise ValueError(f"Servant {servant_name} is already banned")
        
        self.banned_servants.add(servant_name)
        
        if banned_by is None:
            # System ban
            if servant_name not in self.system_bans:
                self.system_bans.append(servant_name)
        else:
            # Captain ban
            if banned_by not in self.captain_bans:
                self.captain_bans[banned_by] = []
            self.captain_bans[banned_by].append(servant_name)
    
    def is_servant_available(self, servant_name: str) -> bool:
        """Check if a servant is available for selection"""
        return (servant_name in self.available_servants and 
                servant_name not in self.banned_servants)
    
    def get_available_servants(self) -> Set[str]:
        """Get all currently available servants"""
        return self.available_servants - self.banned_servants
    
    def assign_servant_to_player(self, user_id: int, servant_name: str) -> None:
        """Assign a servant to a player"""
        player = self.get_player(user_id)
        if not player:
            raise ValueError(f"Player {user_id} not found")
        
        if not self.is_servant_available(servant_name):
            raise ValueError(f"Servant {servant_name} is not available")
        
        # Check if another player has this servant
        for other_player in self.players.values():
            if other_player.selected_servant == servant_name and other_player.user_id != user_id:
                raise ValueError(f"Servant {servant_name} is already selected by another player")
        
        player.select_servant(servant_name)
        self.confirmed_servants[user_id] = servant_name
    
    # ===================
    # Team Selection Methods
    # ===================
    
    def start_team_selection(self, first_pick_captain_id: int) -> None:
        """Start the team selection phase"""
        if not self.is_captain(first_pick_captain_id):
            raise ValueError(f"User {first_pick_captain_id} is not a captain")
        
        self.first_pick_captain = first_pick_captain_id
        self.current_picking_captain = first_pick_captain_id
        self.team_selection_round = 1
        
        # Initialize picking progress
        for captain_id in self.captains:
            self.picks_this_round[captain_id] = 0
            self.team_selection_progress[captain_id] = {}
    
    def assign_player_to_team(self, captain_id: int, player_id: int, team_number: int) -> None:
        """Assign a player to a team during team selection"""
        if not self.is_captain(captain_id):
            raise ValueError(f"User {captain_id} is not a captain")
        
        player = self.get_player(player_id)
        if not player:
            raise ValueError(f"Player {player_id} not found")
        
        if player.is_assigned_to_team:
            raise ValueError(f"Player {player_id} is already assigned to a team")
        
        team = self.teams.get_team_by_number(team_number)
        if not team.can_add_player():
            raise ValueError(f"Team {team_number} is full")
        
        # Assign player to team
        player.assign_to_team(team_number)
        team.add_player(player_id)
    
    def get_unassigned_players(self) -> List[Player]:
        """Get list of players not yet assigned to teams"""
        return [player for player in self.players.values() 
                if not player.is_assigned_to_team]
    
    # ===================
    # State Query Methods
    # ===================
    
    def get_phase_progress(self) -> Dict[str, Any]:
        """Get current phase progress information"""
        progress = {
            "phase": self.phase.value,
            "total_players": self.total_players_needed,
            "current_players": self.current_player_count,
            "is_full": self.is_full,
            "can_start": self.can_start
        }
        
        if self.phase == DraftPhase.CAPTAIN_VOTING:
            progress["captain_voting"] = {
                "votes_cast": dict(self.captain_voting_progress),
                "time_remaining": self._get_captain_voting_time_remaining()
            }
        elif self.phase == DraftPhase.SERVANT_SELECTION:
            progress["servant_selection"] = {
                "completed": dict(self.selection_progress),
                "time_remaining": self._get_selection_time_remaining()
            }
        elif self.phase == DraftPhase.TEAM_SELECTION:
            progress["team_selection"] = {
                "current_captain": self.current_picking_captain,
                "round": self.team_selection_round,
                "picks_this_round": dict(self.picks_this_round)
            }
        
        return progress
    
    def _get_captain_voting_time_remaining(self) -> Optional[int]:
        """Get remaining time for captain voting"""
        if self.captain_voting_start_time is None:
            return None
        elapsed = time.time() - self.captain_voting_start_time
        remaining = max(0, self.captain_voting_time_limit - elapsed)
        return int(remaining)
    
    def _get_selection_time_remaining(self) -> Optional[int]:
        """Get remaining time for servant selection"""
        start_time = (self.reselection_start_time 
                     if self.phase == DraftPhase.SERVANT_RESELECTION 
                     else self.selection_start_time)
        if start_time is None:
            return None
        
        time_limit = (self.reselection_time_limit 
                     if self.phase == DraftPhase.SERVANT_RESELECTION 
                     else self.selection_time_limit)
        
        elapsed = time.time() - start_time
        remaining = max(0, time_limit - elapsed)
        return int(remaining)
    
    # ===================
    # Validation Methods
    # ===================
    
    def validate_state(self) -> List[str]:
        """Validate current draft state and return any issues"""
        issues = []
        
        # Basic validation
        if self.team_size < 1:
            issues.append("Team size must be positive")
        
        if len(self.players) > self.total_players_needed:
            issues.append("Too many players in draft")
        
        # Phase-specific validation
        if self.phase == DraftPhase.CAPTAIN_VOTING:
            if len(self.captains) > 2:
                issues.append("Too many captains selected")
        
        elif self.phase == DraftPhase.TEAM_SELECTION:
            if not self.teams.both_have_captains:
                issues.append("Both teams must have captains for team selection")
            
            if self.current_picking_captain not in self.captains:
                issues.append("Current picking captain is not valid")
        
        elif self.phase == DraftPhase.COMPLETED:
            if not self.teams.is_complete:
                issues.append("Teams are not complete")
        
        return issues
