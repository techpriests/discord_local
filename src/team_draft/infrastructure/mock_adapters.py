"""
Mock Adapters for Testing

Mock implementations of interfaces for testing without Discord dependencies.
"""

from typing import Optional, List, Dict, Any
from ..application.interfaces import INotificationService, IPermissionChecker, IUIPresenter
from ..application.dto import DraftDTO


class MockNotificationService(INotificationService):
    """Mock notification service for testing"""
    
    def __init__(self):
        self.sent_messages = []
    
    async def send_ephemeral_message(self, user_id: int, message: str) -> None:
        self.sent_messages.append(f"EPHEMERAL to {user_id}: {message}")
    
    async def send_channel_message(self, channel_id: int, message: str) -> None:
        self.sent_messages.append(f"CHANNEL {channel_id}: {message}")
    
    async def send_error_message(self, user_id: int, error: str) -> None:
        self.sent_messages.append(f"ERROR to {user_id}: {error}")


class MockPermissionChecker(IPermissionChecker):
    """Mock permission checker for testing"""
    
    def __init__(self):
        self.bot_owners = set()
        self.draft_starters = {}
    
    async def is_bot_owner(self, user_id: int) -> bool:
        return user_id in self.bot_owners
    
    async def can_start_draft(self, user_id: int, channel_id: int) -> bool:
        return True  # Allow all for testing
    
    async def can_force_start(self, user_id: int, draft) -> bool:
        return user_id in self.bot_owners or user_id == draft.started_by_user_id
    
    def set_bot_owner(self, user_id: int):
        """Helper for testing"""
        self.bot_owners.add(user_id)


class MockUIPresenter(IUIPresenter):
    """Mock UI presenter for testing"""
    
    def __init__(self):
        self.shown_views = []
        self.updated_status = []
    
    async def show_draft_lobby(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"LOBBY: {draft_dto.channel_id}")
    
    async def show_captain_voting(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"CAPTAIN_VOTING: {draft_dto.channel_id}")
    
    async def show_servant_selection(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"SERVANT_SELECTION: {draft_dto.channel_id}")
    
    async def show_team_selection(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"TEAM_SELECTION: {draft_dto.channel_id}")
    
    async def show_game_results(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"GAME_RESULTS: {draft_dto.channel_id}")
    
    async def update_draft_status(self, draft_dto: DraftDTO) -> None:
        self.updated_status.append(f"UPDATE: {draft_dto.channel_id} - {draft_dto.phase}")
