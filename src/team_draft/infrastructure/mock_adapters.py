"""
Mock Adapters for Testing

Mock implementations of interfaces for testing without Discord dependencies.
"""

from typing import Optional, List, Dict, Any
from ..application.interfaces import INotificationService, IPermissionChecker, IUIPresenter, IThreadService
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
    
    async def show_captain_voting_progress(self, draft_dto: DraftDTO, progress_details: Dict[str, Any]) -> None:
        print(f"Mock: Captain voting progress - {progress_details}")
    
    async def show_team_selection_progress(self, draft_dto: DraftDTO, round_info: Dict[str, Any]) -> None:
        print(f"Mock: Team selection progress - Round {round_info.get('round', 'N/A')}")
    
    async def show_dice_roll_results(self, draft_dto: DraftDTO, dice_results: Dict[int, int]) -> None:
        print(f"Mock: Dice roll results - {dice_results}")
    
    async def show_system_ban_results(self, draft_dto: DraftDTO, banned_servants: List[str]) -> None:
        print(f"Mock: System bans - {banned_servants}")
    
    async def cleanup_channel(self, channel_id: int) -> None:
        print(f"Mock: Cleanup channel {channel_id}")
    
    async def show_servant_ban_phase(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"SERVANT_BAN: {draft_dto.channel_id}")
    
    async def update_captain_ban_progress(self, draft_dto: DraftDTO) -> None:
        print(f"Mock: Captain ban progress - Channel {draft_dto.channel_id}")
    
    async def show_servant_selection(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"SERVANT_SELECTION: {draft_dto.channel_id}")
    
    async def update_servant_selection_progress(self, draft_dto: DraftDTO) -> None:
        print(f"Mock: Servant selection progress - Channel {draft_dto.channel_id}")
    
    async def show_servant_reselection(self, draft_dto: DraftDTO) -> None:
        self.shown_views.append(f"SERVANT_RESELECTION: {draft_dto.channel_id}")


class MockThreadService(IThreadService):
    """Mock thread service for testing"""
    
    async def create_draft_thread(self, channel_id: int, thread_name: str, team_format: str, players: List[str]) -> Optional[int]:
        """Mock thread creation"""
        thread_id = 999999  # Mock thread ID
        print(f"Mock: Created thread '{thread_name}' for format {team_format} in channel {channel_id}")
        return thread_id
    
    async def send_to_thread_and_main(self, channel_id: int, thread_id: Optional[int], embed, view=None) -> None:
        """Mock hybrid messaging"""
        if thread_id:
            print(f"Mock: Sent message to thread {thread_id} and main channel {channel_id}")
        else:
            print(f"Mock: Sent message to main channel {channel_id}")
