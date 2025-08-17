"""
Dependency Injection Configuration

Central container that wires up all dependencies for the team draft system.
"""

from typing import Dict, Any
from ..application.interfaces import (
    IDraftRepository,
    IUIPresenter,
    IMatchRecorder,
    IBalanceCalculator,
    INotificationService,
    IRosterService,
    IPermissionChecker,
    IDraftConfiguration,
    IThreadService
)
from ..application.draft_service import DraftApplicationService
from .storage_adapter import MemoryDraftRepository
from .balance_adapter import AutoBalanceAdapter
from .match_recorder_adapter import MatchRecorderAdapter
from .roster_adapter import RosterServiceAdapter
from .discord_adapter import DiscordNotificationService, DiscordPermissionChecker
from .draft_config_adapter import DraftConfigurationAdapter
from .thread_adapter import DiscordThreadAdapter


class DraftContainer:
    """
    Dependency injection container for the team draft system.
    
    Centralizes all dependency wiring and provides factory methods
    for creating properly configured services.
    """
    
    def __init__(self, bot=None):
        """
        Initialize container with Discord bot instance.
        
        Args:
            bot: Discord bot instance (optional for testing)
        """
        self.bot = bot
        self._services: Dict[str, Any] = {}
        self._setup_dependencies()
    
    def _setup_dependencies(self):
        """Setup all service dependencies"""
        # Infrastructure adapters
        self._services['draft_repository'] = MemoryDraftRepository()
        self._services['balance_calculator'] = AutoBalanceAdapter()
        self._services['match_recorder'] = MatchRecorderAdapter()
        self._services['roster_service'] = RosterServiceAdapter()
        self._services['draft_configuration'] = DraftConfigurationAdapter()
        
        # Discord-specific services (require bot instance)
        if self.bot:
            self._services['notification_service'] = DiscordNotificationService(self.bot)
            self._services['permission_checker'] = DiscordPermissionChecker(self.bot)
            self._services['thread_service'] = DiscordThreadAdapter(self.bot)
            # UI presenter will be set by presentation layer
            self._services['ui_presenter'] = None
        else:
            # Mock services for testing
            from .mock_adapters import (
                MockNotificationService, 
                MockPermissionChecker, 
                MockUIPresenter,
                MockThreadService
            )
            self._services['notification_service'] = MockNotificationService()
            self._services['permission_checker'] = MockPermissionChecker()
            self._services['ui_presenter'] = MockUIPresenter()
            self._services['thread_service'] = MockThreadService()
    
    def get_draft_service(self) -> DraftApplicationService:
        """Get configured draft application service"""
        if 'draft_service' not in self._services:
            self._services['draft_service'] = DraftApplicationService(
                draft_repository=self.get_draft_repository(),
                ui_presenter=self.get_ui_presenter(),
                match_recorder=self.get_match_recorder(),
                balance_calculator=self.get_balance_calculator(),
                notification_service=self.get_notification_service(),
                thread_service=self.get_thread_service()
            )
        return self._services['draft_service']
    
    def get_draft_repository(self) -> IDraftRepository:
        """Get draft repository"""
        return self._services['draft_repository']
    
    def get_ui_presenter(self) -> IUIPresenter:
        """Get UI presenter"""
        return self._services['ui_presenter']
    
    def get_match_recorder(self) -> IMatchRecorder:
        """Get match recorder"""
        return self._services['match_recorder']
    
    def get_balance_calculator(self) -> IBalanceCalculator:
        """Get balance calculator"""
        return self._services['balance_calculator']
    
    def get_notification_service(self) -> INotificationService:
        """Get notification service"""
        return self._services['notification_service']
    
    def get_roster_service(self) -> IRosterService:
        """Get roster service"""
        return self._services['roster_service']
    
    def get_permission_checker(self) -> IPermissionChecker:
        """Get permission checker"""
        return self._services['permission_checker']
    
    def get_draft_configuration(self) -> IDraftConfiguration:
        """Get draft configuration"""
        return self._services['draft_configuration']
    
    def get_thread_service(self) -> IThreadService:
        """Get thread service"""
        return self._services['thread_service']
    
    def set_ui_presenter(self, presenter: IUIPresenter) -> None:
        """Set UI presenter (called by presentation layer)"""
        self._services['ui_presenter'] = presenter
        # Recreate draft service with new presenter
        if 'draft_service' in self._services:
            del self._services['draft_service']
    
    def get_bot(self):
        """Get Discord bot instance"""
        return self.bot
    
    def cleanup(self) -> None:
        """Cleanup resources"""
        # Clear all drafts from memory
        if 'draft_repository' in self._services:
            repo = self._services['draft_repository']
            if hasattr(repo, 'clear_all_drafts'):
                repo.clear_all_drafts()
        
        # Clear service cache
        self._services.clear()


# Global container instance
_container: DraftContainer = None


def get_container() -> DraftContainer:
    """Get global container instance"""
    global _container
    if _container is None:
        _container = DraftContainer()
    return _container


def initialize_container(bot=None) -> DraftContainer:
    """Initialize global container with bot instance"""
    global _container
    _container = DraftContainer(bot)
    return _container


def cleanup_container() -> None:
    """Cleanup global container"""
    global _container
    if _container:
        _container.cleanup()
        _container = None
