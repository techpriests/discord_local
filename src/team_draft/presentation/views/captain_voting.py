"""
Captain Voting View

MVP View for captain voting UI - preserves existing user experience.
"""

import discord
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ..presenters.draft_presenter import DraftPresenter
    from ...application.dto import PlayerDTO


class CaptainVotingView(discord.ui.View):
    """
    Captain voting view with candidate buttons.
    
    Preserves all existing voting behavior while using presenter pattern.
    """
    
    def __init__(self, presenter: "DraftPresenter", channel_id: int, players: List["PlayerDTO"]):
        super().__init__(timeout=120)  # 2 minute timeout
        self.presenter = presenter
        self.channel_id = channel_id
        
        # Add voting buttons for each player - preserves existing layout
        for i, player in enumerate(players[:10]):  # Limit to 10 buttons (Discord limit)
            button = CaptainVoteButton(player.user_id, player.username, i + 1)
            self.add_item(button)
    
    async def on_timeout(self) -> None:
        """Handle view timeout - preserves existing timeout behavior"""
        try:
            # Auto-finalize voting or handle timeout
            await self.presenter.handle_captain_voting_timeout(self.channel_id)
        except Exception:
            pass  # Graceful failure


class CaptainVoteButton(discord.ui.Button):
    """Captain vote button - preserves existing functionality"""
    
    def __init__(self, player_id: int, username: str, number: int):
        super().__init__(
            label=f"{number}. {username}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"vote_{player_id}"
        )
        self.player_id = player_id
        self.username = username
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle vote button click - preserves existing voting logic"""
        view: CaptainVotingView = self.view
        user = interaction.user
        
        # Route through presenter - preserves all validation and responses
        await view.presenter.handle_captain_vote(
            interaction=interaction,
            voter_id=user.id,
            candidate_id=self.player_id,
            channel_id=view.channel_id
        )
