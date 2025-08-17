"""
Application Layer Interfaces (Ports)

Defines contracts between application layer and infrastructure adapters.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from ..domain.entities.draft import Draft
from ..domain.entities.player import Player
from .dto import DraftDTO, PlayerDTO


# Repository Interfaces
class IDraftRepository(ABC):
    """Repository for draft persistence"""
    
    @abstractmethod
    async def save_draft(self, draft: Draft) -> None:
        """Save a draft"""
        pass
    
    @abstractmethod
    async def get_draft(self, channel_id: int) -> Optional[Draft]:
        """Get draft by channel ID"""
        pass
    
    @abstractmethod
    async def delete_draft(self, channel_id: int) -> None:
        """Delete a draft"""
        pass
    
    @abstractmethod
    async def get_active_drafts(self) -> List[Draft]:
        """Get all active drafts"""
        pass


# External Service Interfaces
class IMatchRecorder(ABC):
    """Interface for recording match results"""
    
    @abstractmethod
    async def record_match(self, draft: Draft, winner: Optional[int], score: Optional[str]) -> None:
        """Record match result"""
        pass


class IBalanceCalculator(ABC):
    """Interface for team balance calculations"""
    
    @abstractmethod
    async def calculate_team_balance(self, draft: Draft) -> Dict[str, Any]:
        """Calculate team balance and suggestions"""
        pass
    
    @abstractmethod
    async def auto_balance_teams(self, draft: Draft, algorithm: str) -> Dict[str, Any]:
        """Perform automatic team balancing"""
        pass


class IRosterService(ABC):
    """Interface for player roster management"""
    
    @abstractmethod
    async def get_player_rating(self, user_id: int, guild_id: int) -> Optional[float]:
        """Get player rating"""
        pass
    
    @abstractmethod
    async def update_player_rating(self, user_id: int, guild_id: int, rating: float) -> None:
        """Update player rating"""
        pass


# UI Presenter Interfaces
class IUIPresenter(ABC):
    """Interface for UI presentation layer"""
    
    @abstractmethod
    async def show_draft_lobby(self, draft_dto: DraftDTO) -> None:
        """Display draft lobby UI"""
        pass
    
    @abstractmethod
    async def show_captain_voting(self, draft_dto: DraftDTO) -> None:
        """Display captain voting UI"""
        pass
    
    @abstractmethod
    async def show_servant_selection(self, draft_dto: DraftDTO) -> None:
        """Display servant selection UI"""
        pass
    
    @abstractmethod
    async def show_team_selection(self, draft_dto: DraftDTO) -> None:
        """Display team selection UI"""
        pass
    
    @abstractmethod
    async def show_game_results(self, draft_dto: DraftDTO) -> None:
        """Display game results UI"""
        pass
    
    @abstractmethod
    async def update_draft_status(self, draft_dto: DraftDTO) -> None:
        """Update draft status display"""
        pass


class INotificationService(ABC):
    """Interface for sending notifications"""
    
    @abstractmethod
    async def send_ephemeral_message(self, user_id: int, message: str) -> None:
        """Send ephemeral message to user"""
        pass
    
    @abstractmethod
    async def send_channel_message(self, channel_id: int, message: str) -> None:
        """Send message to channel"""
        pass
    
    @abstractmethod
    async def send_error_message(self, user_id: int, error: str) -> None:
        """Send error message to user"""
        pass


# Discord-specific Interfaces
class IDiscordInteractionHandler(ABC):
    """Interface for handling Discord interactions"""
    
    @abstractmethod
    async def handle_button_click(self, interaction_data: Dict[str, Any]) -> None:
        """Handle button click interaction"""
        pass
    
    @abstractmethod
    async def handle_dropdown_selection(self, interaction_data: Dict[str, Any]) -> None:
        """Handle dropdown selection"""
        pass
    
    @abstractmethod
    async def handle_modal_submission(self, interaction_data: Dict[str, Any]) -> None:
        """Handle modal form submission"""
        pass


class IPermissionChecker(ABC):
    """Interface for checking user permissions"""
    
    @abstractmethod
    async def is_bot_owner(self, user_id: int) -> bool:
        """Check if user is bot owner"""
        pass
    
    @abstractmethod
    async def can_start_draft(self, user_id: int, channel_id: int) -> bool:
        """Check if user can start a draft"""
        pass
    
    @abstractmethod
    async def can_force_start(self, user_id: int, draft: Draft) -> bool:
        """Check if user can force start a draft"""
        pass


# Configuration Interfaces
class IDraftConfiguration(ABC):
    """Interface for draft configuration"""
    
    @abstractmethod
    def get_team_selection_patterns(self) -> Dict[int, List[Dict[str, int]]]:
        """Get team selection patterns for different team sizes"""
        pass
    
    @abstractmethod
    def get_time_limits(self) -> Dict[str, int]:
        """Get time limits for different phases"""
        pass
    
    @abstractmethod
    def get_servant_configuration(self) -> Dict[str, Any]:
        """Get servant configuration (tiers, categories, etc.)"""
        pass
