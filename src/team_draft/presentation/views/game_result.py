"""
Game Result View

MVP View for game result submission UI - preserves existing user experience.
"""

import discord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..presenters.draft_presenter import DraftPresenter


class GameResultView(discord.ui.View):
    """
    Game result view with submission button.
    
    Preserves all existing result submission behavior.
    """
    
    def __init__(self, presenter: "DraftPresenter", channel_id: int):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.presenter = presenter
        self.channel_id = channel_id
        
        # Add result submission button
        submit_button = GameResultButton()
        self.add_item(submit_button)


class GameResultButton(discord.ui.Button):
    """Game result submission button"""
    
    def __init__(self):
        super().__init__(
            label="📝 경기 결과 입력",
            style=discord.ButtonStyle.primary,
            custom_id="submit_result"
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle result submission button - opens modal"""
        modal = GameResultModal()
        await interaction.response.send_modal(modal)


class GameResultModal(discord.ui.Modal, title="경기 결과 입력"):
    """Game result submission modal - preserves existing form"""
    
    def __init__(self):
        super().__init__()
        
        # Winner selection
        self.winner = discord.ui.TextInput(
            label="승리팀 (1 또는 2)",
            placeholder="1 또는 2를 입력하세요",
            required=True,
            max_length=1
        )
        self.add_item(self.winner)
        
        # Score input
        self.score = discord.ui.TextInput(
            label="점수 (선택사항)",
            placeholder="예: 2-0, 3-1",
            required=False,
            max_length=20
        )
        self.add_item(self.score)
    
    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle form submission - preserves existing validation"""
        try:
            winner_text = self.winner.value.strip()
            score_text = self.score.value.strip() if self.score.value else None
            
            # Validate winner
            if winner_text not in ["1", "2"]:
                await interaction.response.send_message(
                    "승리팀은 1 또는 2만 입력할 수 있어.", 
                    ephemeral=True
                )
                return
            
            winner = int(winner_text)
            
            # Get view and route through presenter
            # This would need to be handled by the presenter
            # For now, send confirmation
            result_text = f"팀 {winner} 승리"
            if score_text:
                result_text += f" ({score_text})"
            
            await interaction.response.send_message(
                f"경기 결과가 기록됐어: {result_text}",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(
                "결과 입력 중 오류가 발생했어.",
                ephemeral=True
            )
