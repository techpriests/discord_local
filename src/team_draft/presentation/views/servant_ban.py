"""
Servant Ban View

Discord UI view for the servant ban phase including system bans and captain bans.
Preserves legacy servant ban workflow.
"""

import discord
from discord.ext import commands
from typing import Dict, List, Optional, Any
import logging

from ...application.dto import DraftDTO

logger = logging.getLogger(__name__)


class CaptainBanView(discord.ui.View):
    """
    View for captain ban phase - ephemeral buttons for each captain.
    
    Preserves legacy behavior:
    - Only current banning captain can ban
    - Sequential turn-based banning
    - Public progress display
    """
    
    def __init__(self, draft_dto: DraftDTO, bot_commands):
        super().__init__(timeout=3600.0)  # 1 hour timeout (legacy)
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands
        
        # Create dropdown for servant selection
        self._create_servant_dropdown()
    
    def _create_servant_dropdown(self):
        """Create dropdown with available servants for banning"""
        available_servants = []
        
        # Get available servants (not banned)
        for tier, servants in self.draft_dto.servant_tiers.items():
            for servant in servants:
                if servant not in self.draft_dto.banned_servants:
                    available_servants.append(
                        discord.SelectOption(
                            label=servant,
                            value=servant,
                            description=f"{tier} tier"
                        )
                    )
        
        # Limit to 25 options (Discord limit)
        if len(available_servants) > 25:
            available_servants = available_servants[:25]
        
        if available_servants:
            select = CaptainBanSelect(available_servants, self.draft_dto, self.bot_commands)
            self.add_item(select)


class CaptainBanSelect(discord.ui.Select):
    """Dropdown for captain to select servant to ban"""
    
    def __init__(self, options: List[discord.SelectOption], draft_dto: DraftDTO, bot_commands):
        super().__init__(
            placeholder="서번트를 선택해서 밴해줘...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands
    
    async def callback(self, interaction: discord.Interaction):
        """Handle servant ban selection"""
        try:
            # Check if user is the current banning captain
            if interaction.user.id != self.draft_dto.current_banning_captain:
                await interaction.response.send_message(
                    "지금은 네 차례가 아니야. 순서를 기다려줘.", 
                    ephemeral=True
                )
                return
            
            # Check if captain already completed their ban
            if self.draft_dto.captain_ban_progress.get(interaction.user.id, False):
                await interaction.response.send_message(
                    "이미 밴을 완료했어.", 
                    ephemeral=True
                )
                return
            
            servant_name = self.values[0]
            
            # Apply the ban through the bot commands
            success = await self.bot_commands.apply_captain_ban(
                self.draft_dto.channel_id,
                interaction.user.id,
                servant_name
            )
            
            if success:
                await interaction.response.send_message(
                    f"✅ **{servant_name}**을(를) 밴했어!",
                    ephemeral=False  # Public announcement
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{servant_name}**을(를) 밴할 수 없어. 이미 밴되었거나 사용할 수 없어.",
                    ephemeral=True
                )
        
        except Exception as e:
            logger.error(f"Captain ban selection failed: {e}")
            await interaction.response.send_message(
                "밴 처리 중 오류가 발생했어.",
                ephemeral=True
            )


def create_servant_ban_embed(draft_dto: DraftDTO) -> discord.Embed:
    """Create embed for servant ban phase display"""
    embed = discord.Embed(
        title="🚫 서번트 밴 단계",
        description="시스템 밴과 팀장 밴이 진행되고 있어.",
        color=0xe74c3c  # BAN_COLOR
    )
    
    # Show captains
    if draft_dto.captains:
        captain_names = []
        for captain_id in draft_dto.captains:
            if captain_id in draft_dto.players:
                captain_names.append(draft_dto.players[captain_id]['username'])
        
        if captain_names:
            embed.add_field(
                name="팀장",
                value=" vs ".join(captain_names),
                inline=False
            )
    
    # Show system bans
    if draft_dto.system_bans:
        system_ban_text = ", ".join(draft_dto.system_bans)
        embed.add_field(
            name="문 셀 밴",
            value=system_ban_text,
            inline=False
        )
    
    # Show dice roll results
    if draft_dto.captain_ban_dice_rolls:
        dice_text = ""
        for captain_id, roll in draft_dto.captain_ban_dice_rolls.items():
            if captain_id in draft_dto.players:
                captain_name = draft_dto.players[captain_id]['username']
                dice_text += f"{captain_name}: {roll}\n"
        
        if dice_text:
            embed.add_field(
                name="🎲 주사위 결과",
                value=dice_text.strip(),
                inline=True
            )
    
    # Show current banning captain
    if draft_dto.current_banning_captain and draft_dto.current_banning_captain in draft_dto.players:
        current_captain_name = draft_dto.players[draft_dto.current_banning_captain]['username']
        embed.add_field(
            name="현재 밴 차례",
            value=f"**{current_captain_name}**",
            inline=True
        )
    
    # Show captain ban progress
    if draft_dto.captain_ban_order:
        progress_text = ""
        for i, captain_id in enumerate(draft_dto.captain_ban_order):
            if captain_id in draft_dto.players:
                captain_name = draft_dto.players[captain_id]['username']
                
                if captain_id == draft_dto.current_banning_captain:
                    status = "🎯 현재 차례"
                elif draft_dto.captain_ban_progress.get(captain_id, False):
                    # Show what they banned
                    captain_bans = draft_dto.captain_bans.get(captain_id, [])
                    ban_text = captain_bans[0] if captain_bans else "완료"
                    status = f"✅ 완료 ({ban_text})"
                else:
                    status = "⏳ 대기 중"
                
                progress_text += f"{i+1}. {captain_name}: {status}\n"
        
        if progress_text:
            embed.add_field(
                name="진행 상황",
                value=progress_text.strip(),
                inline=False
            )
    
    return embed
