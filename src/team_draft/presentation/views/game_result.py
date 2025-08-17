"""
Game Result View

Matches legacy game result UI behavior exactly.
"""

import discord
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..presenters.draft_presenter import DraftPresenter


class GameResultView(discord.ui.View):
    """
    Game result view with finish game button - matches legacy behavior exactly.
    
    Features:
    - Single "경기 종료 및 결과 기록" button (red danger style)
    - Permission check (only starter or bot owner)
    - Opens modal for score input in format "12:8"
    """
    
    def __init__(self, presenter: "DraftPresenter", channel_id: int):
        super().__init__(timeout=7200)  # 2 hour timeout like legacy
        self.presenter = presenter
        self.channel_id = channel_id
        
        # Add finish game button (legacy style)
        finish_button = FinishGameButton()
        self.add_item(finish_button)


class FinishGameButton(discord.ui.Button):
    """Finish game button - matches legacy exactly"""
    
    def __init__(self):
        super().__init__(
            label="경기 종료 및 결과 기록",
            style=discord.ButtonStyle.danger,  # Red button like legacy
            custom_id="finish_game"
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle finish game button - matches legacy permission and flow"""
        view: GameResultView = self.view
        
        try:
            # Get draft to check permissions and status
            draft_dto = await view.presenter.draft_service.get_draft_status(view.channel_id)
            if not draft_dto:
                await interaction.response.send_message("드래프트를 찾을 수 없어.", ephemeral=True)
                return
            
            # Check if outcome already recorded
            if hasattr(draft_dto, 'outcome_recorded') and draft_dto.outcome_recorded:
                await interaction.response.send_message("이미 결과가 기록되었어", ephemeral=True)
                return
            
            # Permission check: starter or bot owner only (legacy logic)
            user = interaction.user
            is_owner = False
            try:
                if isinstance(interaction.client, discord.ext.commands.Bot):
                    is_owner = await interaction.client.is_owner(user)
            except Exception:
                is_owner = False
            
            # Check if user is the draft starter
            is_starter = hasattr(draft_dto, 'started_by_user_id') and user.id == draft_dto.started_by_user_id
            
            if not is_starter and not is_owner:
                await interaction.response.send_message("시작자만 결과를 기록할 수 있어", ephemeral=True)
                return
            
            # Open score input modal (legacy behavior)
            modal = GameResultModal(view.presenter, view.channel_id)
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            await interaction.response.send_message("오류가 발생했어. 다시 시도해줘.", ephemeral=True)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to handle finish game button: {e}")


class GameResultModal(discord.ui.Modal, title="경기 결과 입력"):
    """Game result modal - matches legacy score format exactly"""
    
    def __init__(self, presenter: "DraftPresenter", channel_id: int):
        super().__init__(timeout=300.0)  # 5 minute timeout like legacy
        self.presenter = presenter
        self.channel_id = channel_id
        
        # Score input with legacy format
        self.score_input = discord.ui.TextInput(
            label="팀1 점수(왼쪽):팀2 점수(오른쪽) (예: 12:8)",
            placeholder="12:8",
            required=True,
            max_length=10
        )
        self.add_item(self.score_input)
    
    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle score submission - matches legacy validation exactly"""
        try:
            text = str(self.score_input.value).strip()
            
            # Legacy regex validation for score format
            m = re.match(r"^(\d{1,2})\s*[:：]\s*(\d{1,2})$", text)
            if not m:
                await interaction.response.send_message("형식이 올바르지 않아. 예: 12:8", ephemeral=True)
                return
            
            a = int(m.group(1))
            b = int(m.group(2))
            
            # No ties allowed (legacy rule)
            if a == b:
                await interaction.response.send_message("무승부는 허용되지 않아", ephemeral=True)
                return
            
            # Legacy requirement: one team must score 12 (FGO match rule)
            if a != 12 and b != 12:
                await interaction.response.send_message("한 팀은 반드시 12점을 얻어야 해", ephemeral=True)
                return
            
            # Determine winner
            winner = 1 if a > b else 2
            score_str = f"{a}:{b}"
            
            # Record result through draft service
            success = await self.presenter.draft_service.record_match_result(
                self.channel_id, winner, score_str
            )
            
            if success:
                await interaction.response.send_message("결과를 기록했어!", ephemeral=True)
                
                # Disable the finish button by clearing the view (legacy behavior)
                try:
                    # Get the original message and remove the view
                    if self.channel_id in self.presenter.active_views:
                        del self.presenter.active_views[self.channel_id]
                    
                    # Show completion message
                    embed = discord.Embed(
                        title="✅ 경기 결과 기록 완료",
                        description=f"**팀 {winner} 승리** (점수: {score_str})\n\n경기가 완료되었습니다.",
                        color=0x27ae60
                    )
                    
                    # Broadcast completion to thread and main channel
                    await self.presenter.thread_service.send_to_thread_and_main(
                        channel_id=self.channel_id,
                        thread_id=(await self.presenter.draft_service.get_draft_status(self.channel_id)).thread_id,
                        embed=embed
                    )
                    
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to update after result recording: {e}")
            else:
                await interaction.response.send_message("결과 저장에 실패했어", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message("결과 입력 중 오류가 발생했어.", ephemeral=True)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to submit game result: {e}")