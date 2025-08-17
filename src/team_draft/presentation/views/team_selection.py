"""
Team Selection View

MVP View for team selection UI - preserves existing user experience.
"""

import discord
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ..presenters.draft_presenter import DraftPresenter
    from ...application.dto import PlayerDTO


class TeamSelectionView(discord.ui.View):
    """
    Team selection view with player dropdown.
    
    Preserves all existing selection behavior while using presenter pattern.
    """
    
    def __init__(self, presenter: "DraftPresenter", channel_id: int, available_players: List["PlayerDTO"]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.presenter = presenter
        self.channel_id = channel_id
        
        # Add player selection dropdown - preserves existing layout
        if available_players:
            dropdown = PlayerSelectionDropdown(available_players)
            self.add_item(dropdown)
    
    async def on_timeout(self) -> None:
        """Handle view timeout"""
        try:
            await self.presenter.handle_team_selection_timeout(self.channel_id)
        except Exception:
            pass


class PlayerSelectionDropdown(discord.ui.Select):
    """Player selection dropdown - preserves existing functionality"""
    
    def __init__(self, available_players: List["PlayerDTO"]):
        options = []
        for i, player in enumerate(available_players[:25]):  # Discord limit
            options.append(discord.SelectOption(
                label=player.username,
                value=str(player.user_id),
                description=f"Servant: {player.selected_servant or 'None'}"
            ))
        
        super().__init__(
            placeholder="Choose a player to add to your team...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection - preserves existing behavior"""
        view: TeamSelectionView = self.view
        
        if not self.values:
            await interaction.response.send_message("No player selected.", ephemeral=True)
            return
        
        selected_player_id = int(self.values[0])
        
        # Route through presenter - preserves all validation and responses
        await view.presenter.handle_team_player_assignment(
            interaction=interaction,
            captain_id=interaction.user.id,
            player_id=selected_player_id,
            channel_id=view.channel_id
        )
