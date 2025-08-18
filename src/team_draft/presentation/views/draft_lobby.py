"""
Draft Lobby View

MVP View for draft lobby UI - preserves existing user experience.
"""

import discord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..presenters.draft_presenter import DraftPresenter


class DraftLobbyView(discord.ui.View):
    """
    Draft lobby view with join/leave/force start functionality.
    
    Preserves all existing UI behavior while using presenter pattern.
    """
    
    def __init__(self, presenter: "DraftPresenter", channel_id: int):
        super().__init__(timeout=3600)  # 1 hour timeout (legacy)
        self.presenter = presenter
        self.channel_id = channel_id
        
        # Add buttons - preserves existing layout
        self.add_item(JoinButton())
        self.add_item(LeaveButton())
        self.add_item(ForceStartButton())
    
    async def on_timeout(self) -> None:
        """Handle view timeout - preserves existing cleanup behavior"""
        try:
            await self.presenter.handle_lobby_timeout(self.channel_id)
        except Exception:
            pass  # Graceful failure


class JoinButton(discord.ui.Button):
    """Join draft button - preserves existing functionality"""
    
    def __init__(self):
        super().__init__(
            label="참가", 
            style=discord.ButtonStyle.success, 
            custom_id="join"
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle join button click - preserves existing validation and responses"""
        view: DraftLobbyView = self.view
        user = interaction.user
        
        # Preserve existing bot check
        if user.bot:
            await interaction.response.send_message("봇은 참가할 수 없어", ephemeral=True)
            return
        
        # Route through presenter - preserves all business logic and responses
        await view.presenter.handle_join_request(
            interaction=interaction,
            user_id=user.id,
            username=user.display_name,
            channel_id=view.channel_id
        )


class LeaveButton(discord.ui.Button):
    """Leave draft button - preserves existing functionality"""
    
    def __init__(self):
        super().__init__(
            label="취소", 
            style=discord.ButtonStyle.secondary, 
            custom_id="leave"
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle leave button click - preserves existing behavior"""
        view: DraftLobbyView = self.view
        user = interaction.user
        
        # Route through presenter - preserves all validation and responses
        await view.presenter.handle_leave_request(
            interaction=interaction,
            user_id=user.id,
            channel_id=view.channel_id
        )


class ForceStartButton(discord.ui.Button):
    """Force start button - preserves existing functionality"""
    
    def __init__(self):
        super().__init__(
            label="강제 시작", 
            style=discord.ButtonStyle.primary, 
            custom_id="force_start"
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle force start - preserves existing permission checks and behavior"""
        view: DraftLobbyView = self.view
        user = interaction.user
        
        # Route through presenter - preserves all permission logic and responses
        await view.presenter.handle_force_start_request(
            interaction=interaction,
            user_id=user.id,
            channel_id=view.channel_id
        )
