"""
Team Selection View

Implements legacy batch selection behavior where captains can select multiple players
before confirming, with the ability to cancel individual selections.
"""

import discord
from typing import TYPE_CHECKING, List, Dict, Set

if TYPE_CHECKING:
    from ..presenters.draft_presenter import DraftPresenter
    from ...application.dto import PlayerDTO, DraftDTO


class TeamSelectionView(discord.ui.View):
    """
    Team selection view with batch selection and cancellation support.
    
    Preserves legacy behavior:
    - Captains can select multiple players (1-2 depending on round/pattern)
    - Shows pending selections as buttons that can be cancelled
    - Requires confirmation before finalizing selections
    """
    
    def __init__(self, presenter: "DraftPresenter", draft_dto: "DraftDTO", available_players: List["PlayerDTO"]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.presenter = presenter
        self.draft_dto = draft_dto
        self.channel_id = draft_dto.channel_id
        self.available_players = available_players
        
        # Initialize pending selections for current captain
        current_captain = draft_dto.current_picking_captain
        self.pending_selections: Set[int] = set()
        
        # Get current round info for max picks
        self.max_picks = self._get_max_picks_for_current_captain()
        
        # Build UI components
        self._build_player_selection_dropdown()
        self._build_pending_selection_buttons()
        self._build_confirmation_button()
    
    def _get_max_picks_for_current_captain(self) -> int:
        """Get maximum picks allowed for current captain in this round"""
        try:
            # This would need to be passed from presenter or calculated
            # For now, default to reasonable values based on team size
            team_size = self.draft_dto.team_size
            round_num = getattr(self.draft_dto, 'team_selection_round', 1)
            
            # Simplified pattern logic - should match domain service
            if team_size == 2:
                return 1
            elif team_size == 3:
                return 2 if round_num == 1 else 1
            elif team_size == 5:
                return 2 if round_num in [1, 2] else 1
            elif team_size == 6:
                return 2 if round_num in [1, 2] else 1
            else:
                return 1
        except Exception:
            return 1
    
    def _build_player_selection_dropdown(self):
        """Build dropdown for selecting players"""
        if not self.available_players:
            return
            
        # Only show dropdown if we can still pick more players
        if len(self.pending_selections) < self.max_picks:
            dropdown = PlayerSelectionDropdown(self.available_players, self.pending_selections)
            self.add_item(dropdown)
    
    def _build_pending_selection_buttons(self):
        """Build buttons for pending selections (for cancellation)"""
        if not self.pending_selections:
            return
            
        # Add cancel buttons for each pending selection
        for player_id in list(self.pending_selections)[:5]:  # Limit to 5 buttons per row
            player = next((p for p in self.available_players if p.user_id == player_id), None)
            if player:
                cancel_button = CancelSelectionButton(player_id, player.username)
                self.add_item(cancel_button)
    
    def _build_confirmation_button(self):
        """Build confirmation button if we have selections to confirm"""
        if self.pending_selections:
            confirm_button = ConfirmTeamSelectionButton(self.max_picks, len(self.pending_selections))
            self.add_item(confirm_button)
    
    def refresh_ui(self):
        """Refresh the UI components after selection changes"""
        # Clear all components
        self.clear_items()
        
        # Rebuild components
        self._build_player_selection_dropdown()
        self._build_pending_selection_buttons()
        self._build_confirmation_button()
    
    async def add_pending_selection(self, player_id: int) -> bool:
        """Add a player to pending selections"""
        if len(self.pending_selections) >= self.max_picks:
            return False
            
        self.pending_selections.add(player_id)
        self.refresh_ui()
        return True
    
    async def remove_pending_selection(self, player_id: int) -> bool:
        """Remove a player from pending selections"""
        if player_id not in self.pending_selections:
            return False
            
        self.pending_selections.discard(player_id)
        self.refresh_ui()
        return True
    
    async def on_timeout(self) -> None:
        """Handle view timeout"""
        try:
            await self.presenter.handle_team_selection_timeout(self.channel_id)
        except Exception:
            pass


class PlayerSelectionDropdown(discord.ui.Select):
    """Dropdown for selecting players to add to pending selections"""
    
    def __init__(self, available_players: List["PlayerDTO"], pending_selections: Set[int]):
        # Filter out already pending players
        selectable_players = [p for p in available_players if p.user_id not in pending_selections]
        
        options = []
        for i, player in enumerate(selectable_players[:25]):  # Discord limit
            options.append(discord.SelectOption(
                label=player.username,
                value=str(player.user_id),
                description=f"Servant: {player.selected_servant or 'None'}"
            ))
        
        super().__init__(
            placeholder="팀원을 선택하세요",
            min_values=1,
            max_values=min(len(options), 5),  # Allow multiple selections up to 5
            options=options,
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection from dropdown"""
        view: TeamSelectionView = self.view
        
        if not self.values:
            await interaction.response.send_message("선택된 플레이어가 없어.", ephemeral=True)
            return
        
        # Add all selected players to pending
        added_players = []
        for value in self.values:
            player_id = int(value)
            if await view.add_pending_selection(player_id):
                player = next((p for p in view.available_players if p.user_id == player_id), None)
                if player:
                    added_players.append(player.username)
        
        if added_players:
            current_count = len(view.pending_selections)
            max_picks = view.max_picks
            
            message = f"✅ **{', '.join(added_players)}**을(를) 선택했어!\n"
            message += f"현재 선택: ({current_count}/{max_picks})\n"
            message += "취소하려면 플레이어 이름 버튼을 클릭하고, 확정하려면 '선택 확정' 버튼을 눌러줘."
            
            await interaction.response.edit_message(view=view)
            await interaction.followup.send(message, ephemeral=True)
            
            # Real-time progress update (legacy behavior)
            await view.presenter._update_team_selection_progress_real_time(view.channel_id)
        else:
            await interaction.response.send_message("더 이상 선택할 수 없어.", ephemeral=True)


class CancelSelectionButton(discord.ui.Button):
    """Button to cancel a pending player selection"""
    
    def __init__(self, player_id: int, player_name: str):
        super().__init__(
            label=f"❌ {player_name}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"cancel_{player_id}",
            row=1
        )
        self.player_id = player_id
        self.player_name = player_name
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle cancelling a pending selection"""
        view: TeamSelectionView = self.view
        
        if await view.remove_pending_selection(self.player_id):
            current_count = len(view.pending_selections)
            max_picks = view.max_picks
            
            await interaction.response.edit_message(view=view)
            await interaction.followup.send(
                f"❌ **{self.player_name}**을(를) 선택에서 제거했어!\n"
                f"현재 선택: ({current_count}/{max_picks})",
                ephemeral=True
            )
            
            # Real-time progress update (legacy behavior)
            await view.presenter._update_team_selection_progress_real_time(view.channel_id)
        else:
            await interaction.response.send_message(
                f"**{self.player_name}**은(는) 선택 목록에 없어.",
                ephemeral=True
            )


class ConfirmTeamSelectionButton(discord.ui.Button):
    """Button to confirm all pending team member selections"""
    
    def __init__(self, max_picks: int, current_picks: int):
        # Show different styles based on completion
        if current_picks == max_picks:
            style = discord.ButtonStyle.success
            label = f"✅ 선택 확정 ({current_picks}/{max_picks})"
        else:
            style = discord.ButtonStyle.primary
            label = f"⏳ 선택 확정 ({current_picks}/{max_picks})"
            
        super().__init__(
            label=label,
            style=style,
            custom_id="confirm_team_selection",
            row=2
        )
        self.max_picks = max_picks
        self.current_picks = current_picks
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle team selection confirmation"""
        view: TeamSelectionView = self.view
        captain_id = interaction.user.id
        
        # Validate selection count
        pending_count = len(view.pending_selections)
        if pending_count != self.max_picks:
            await interaction.response.send_message(
                f"이번 라운드에서는 정확히 {self.max_picks}명을 선택해야 해. (현재: {pending_count}명)",
                ephemeral=True
            )
            return
        
        # Confirm selections through presenter
        success = await view.presenter.confirm_team_selections(
            interaction=interaction,
            captain_id=captain_id,
            channel_id=view.channel_id,
            selected_player_ids=list(view.pending_selections)
        )
        
        if success:
            # Get names of confirmed players
            confirmed_names = []
            for player_id in view.pending_selections:
                player = next((p for p in view.available_players if p.user_id == player_id), None)
                if player:
                    confirmed_names.append(player.username)
            
            await interaction.response.send_message(
                f"✅ **{', '.join(confirmed_names)}**을(를) 팀원으로 확정했어!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ 확정할 수 없어. 다시 시도해줘.",
                ephemeral=True
            )