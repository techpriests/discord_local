"""
Captain Ban Views

Enhanced captain ban interface with category-based navigation matching servant selection.
Preserves legacy captain ban workflow with private ephemeral interfaces.
"""

import discord
from typing import List
import logging

from ...application.dto import DraftDTO
from .captain_ban_components import (
    PrivateCaptainBanCategoryButton,
    PrivateCaptainBanCharacterDropdown,
    EmptyCaptainBanDropdown,
    ConfirmCaptainBanButton
)

logger = logging.getLogger(__name__)


class CaptainBanView(discord.ui.View):
    """
    View for captain ban phase - single button to open private ban interface.
    
    Preserves legacy behavior:
    - Only current banning captain can ban
    - Sequential turn-based banning
    - Private category-based interface
    - Public progress display
    """
    
    def __init__(self, draft_dto: DraftDTO, presenter):
        super().__init__(timeout=3600.0)  # 1 hour timeout (legacy)
        self.draft_dto = draft_dto
        self.presenter = presenter
        
        # Create button for private ban interface
        self._create_private_ban_button()
    
    def _create_private_ban_button(self):
        """Create button for opening private ban interface"""
        button = GenericCaptainBanInterfaceButton()
        self.add_item(button)


class GenericCaptainBanInterfaceButton(discord.ui.Button):
    """Single button for current captain to open their private ban interface"""
    
    def __init__(self):
        super().__init__(
            label="🎯 서번트 밴하기",
            style=discord.ButtonStyle.danger,
            custom_id="open_my_captain_ban",
            emoji="🚫",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private captain ban interface"""
        try:
            user_id = interaction.user.id
            view: CaptainBanView = self.view
            
            logger.info(f"Captain ban button clicked by user {user_id}")
            
            # Check if user is the current banning captain
            if user_id != view.draft_dto.current_banning_captain:
                await interaction.response.send_message(
                    "지금은 네 차례가 아니야. 순서를 기다려줘.",
                    ephemeral=True
                )
                return
            
            # Check if captain already completed their ban
            if view.draft_dto.captain_ban_progress.get(user_id, False):
                await interaction.response.send_message(
                    "이미 밴을 완료했어.",
                    ephemeral=True
                )
                return
            
            # Create private ban interface
            private_view = PrivateCaptainBanView(view.draft_dto, view.presenter, user_id)
            
            embed = discord.Embed(
                title="🚫 서번트 밴 - 세이버",
                description="**현재 카테고리: 세이버**\n현재 선택: 없음",
                color=0xe74c3c  # ERROR_COLOR (red for bans)
            )
            
            # Show characters in current category with status
            chars_in_category = view.draft_dto.servant_categories["세이버"]
            char_list = []
            for char in chars_in_category:
                if char in view.draft_dto.banned_servants:
                    char_list.append(f"❌ {char} (이미 밴됨)")
                else:
                    char_list.append(f"• {char}")
            
            embed.add_field(name="세이버 서번트 목록", value="\n".join(char_list), inline=False)
            
            await interaction.response.send_message(embed=embed, view=private_view, ephemeral=True)
        
        except Exception as e:
            logger.error(f"Failed to open private captain ban interface: {e}")
            await interaction.response.send_message(
                "밴 인터페이스를 열 수 없어. 다시 시도해줘.", ephemeral=True
            )


class PrivateCaptainBanView(discord.ui.View):
    """Private captain ban interface with category-based navigation"""
    
    def __init__(self, draft_dto: DraftDTO, presenter, user_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft_dto = draft_dto
        self.presenter = presenter
        self.user_id = user_id
        self.current_category = "세이버"  # Default to first category
        self.selected_servant = None
        
        # Add category buttons
        self._add_category_buttons()
        
        # Add character dropdown for current category
        self._add_character_dropdown()
        
        # Add confirmation button
        self._add_confirmation_button()
    
    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft_dto.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):
            button = PrivateCaptainBanCategoryButton(category, i, self.user_id)
            self.add_item(button)
    
    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, (PrivateCaptainBanCharacterDropdown, EmptyCaptainBanDropdown)):
                self.remove_item(item)
        
        # Get available characters for current category (exclude already banned)
        excluded_servants = self.draft_dto.banned_servants.copy()
        
        available_in_category = [
            char for char in self.draft_dto.servant_categories[self.current_category]
            if char not in excluded_servants
        ]
        
        # Check if category has any available characters
        if not available_in_category:
            # Create a disabled dropdown showing no characters available
            dropdown = EmptyCaptainBanDropdown(self.current_category)
            self.add_item(dropdown)
        else:
            # Create normal dropdown with available characters
            dropdown = PrivateCaptainBanCharacterDropdown(
                self.draft_dto, self.presenter, available_in_category, 
                self.current_category, self.user_id
            )
            self.add_item(dropdown)
    
    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmCaptainBanButton(self.user_id)
        self.add_item(button)
    
    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        selection_text = f"현재 선택: {self.selected_servant if self.selected_servant else '없음'}"
        
        embed = discord.Embed(
            title=f"🚫 서번트 밴 - {new_category}",
            description=f"**현재 카테고리: {new_category}**\n{selection_text}",
            color=0xe74c3c  # ERROR_COLOR (red for bans)
        )
        
        # Show characters in current category with status
        chars_in_category = self.draft_dto.servant_categories[new_category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft_dto.banned_servants:
                char_list.append(f"❌ {char} (이미 밴됨)")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{new_category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


def create_captain_ban_embed(draft_dto: DraftDTO) -> discord.Embed:
    """Create embed for captain ban phase"""
    embed = discord.Embed(
        title="🚫 팀장 밴 단계",
        description="이제 각 팀장이 순서대로 1개씩 밴을 선택해.\n밴 내용은 즉시 공개될거야.",
        color=0xe74c3c  # ERROR_COLOR
    )
    
    # Show captains
    captain_names = []
    for captain_id in draft_dto.captains:
        if captain_id in draft_dto.players:
            captain_names.append(draft_dto.players[captain_id]['username'])
    
    if captain_names:
        embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
    
    # Show current system bans
    if hasattr(draft_dto, 'system_bans') and draft_dto.system_bans:
        system_ban_text = ", ".join(draft_dto.system_bans)
        embed.add_field(name="문 셀 밴", value=system_ban_text, inline=False)
    
    # Show dice roll results
    if hasattr(draft_dto, 'captain_ban_dice_rolls') and draft_dto.captain_ban_dice_rolls:
        dice_text = ""
        for captain_id, roll in draft_dto.captain_ban_dice_rolls.items():
            if captain_id in draft_dto.players:
                captain_name = draft_dto.players[captain_id]['username']
                dice_text += f"{captain_name}: {roll}\n"
        
        if dice_text:
            embed.add_field(
                name="주사위 결과",
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
    if hasattr(draft_dto, 'captain_ban_order') and draft_dto.captain_ban_order:
        progress_text = ""
        for i, captain_id in enumerate(draft_dto.captain_ban_order):
            if captain_id in draft_dto.players:
                captain_name = draft_dto.players[captain_id]['username']
                
                if captain_id == draft_dto.current_banning_captain:
                    status = "🎯 현재 차례"
                elif hasattr(draft_dto, 'captain_ban_progress') and draft_dto.captain_ban_progress.get(captain_id, False):
                    # Show what they banned
                    captain_bans = getattr(draft_dto, 'captain_bans', {}).get(captain_id, [])
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
