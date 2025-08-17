"""
Captain Ban UI Components

Category-based captain ban interface matching the legacy servant selection pattern.
Provides private ephemeral interfaces with confirmation buttons.
"""

import discord
import logging
from typing import List
from ...application.dto import DraftDTO

logger = logging.getLogger(__name__)


# ===========================
# Private Captain Ban Interface Components
# ===========================

class PrivateCaptainBanCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private captain ban interface"""
    
    def __init__(self, category: str, index: int, user_id: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_captain_ban_category_{category}_{user_id}",
            row=index // 4
        )
        self.category = category
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        from .captain_ban import PrivateCaptainBanView
        view: PrivateCaptainBanView = self.view
        user_id = interaction.user.id
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 밴 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        await view.update_category(self.category, interaction)


class PrivateCaptainBanCharacterDropdown(discord.ui.Select):
    """Dropdown for character ban selection within a category"""
    
    def __init__(self, draft_dto: DraftDTO, presenter, available_chars: List[str], category: str, user_id: int):
        # Create options from available characters
        options = [
            discord.SelectOption(
                label=char,
                value=char,
                description=f"{category} 클래스"
            )
            for char in available_chars[:25]  # Discord limit
        ]
        
        super().__init__(
            placeholder=f"{category}에서 밴할 서번트를 선택해줘...",
            min_values=1,
            max_values=1,
            options=options,
            row=2
        )
        self.draft_dto = draft_dto
        self.presenter = presenter
        self.category = category
        self.user_id = user_id
    
    async def callback(self, interaction: discord.Interaction):
        """Handle character ban selection"""
        from .captain_ban import PrivateCaptainBanView
        user_id = interaction.user.id
        view: PrivateCaptainBanView = self.view
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 밴 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        servant_name = self.values[0]
        view.selected_servant = servant_name
        
        # Update the interface to show the selection
        selection_text = f"현재 선택: {servant_name}"
        
        embed = discord.Embed(
            title=f"🚫 서번트 밴 - {self.category}",
            description=f"**현재 카테고리: {self.category}**\n{selection_text}\n\n🚫 **{servant_name}**을(를) 임시 선택했어. 확정하려면 확정 버튼을 눌러줘.",
            color=0xe74c3c  # ERROR_COLOR (red for bans)
        )
        
        # Show characters in current category with selection highlighted
        chars_in_category = self.draft_dto.servant_categories[self.category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft_dto.banned_servants:
                char_list.append(f"❌ {char} (이미 밴됨)")
            elif char == servant_name:
                char_list.append(f"🚫 **{char}** (선택됨)")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{self.category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=view)


class EmptyCaptainBanDropdown(discord.ui.Select):
    """Disabled dropdown for categories with no available characters"""
    
    def __init__(self, category: str):
        super().__init__(
            placeholder=f"{category}에 밴할 수 있는 서번트가 없어",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="밴 불가",
                    value="disabled",
                    description="이 카테고리는 모두 밴됨"
                )
            ],
            disabled=True,
            row=2
        )
    
    async def callback(self, interaction: discord.Interaction):
        """This should never be called since the dropdown is disabled"""
        pass


class ConfirmCaptainBanButton(discord.ui.Button):
    """Button to confirm captain ban selection"""
    
    def __init__(self, user_id: int):
        super().__init__(
            label="✅ 밴 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_captain_ban_{user_id}",
            row=3
        )
        self.user_id = user_id
    
    async def callback(self, interaction: discord.Interaction):
        """Handle captain ban confirmation"""
        from .captain_ban import PrivateCaptainBanView
        user_id = interaction.user.id
        view: PrivateCaptainBanView = self.view
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 밴 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        if not view.selected_servant:
            await interaction.response.send_message(
                "먼저 밴할 서번트를 선택해줘.", ephemeral=True
            )
            return
        
        # Apply the ban through the draft system
        from ...presentation.discord_integration import get_integration
        integration = get_integration()
        if integration:
            success = await integration.apply_captain_ban(
                view.draft_dto.channel_id,
                user_id,
                view.selected_servant
            )
        else:
            # Fall back to presenter if available
            success = False  # presenter doesn't have direct apply method
        
        if success:
            embed = discord.Embed(
                title="✅ 밴 완료!",
                description=f"**{view.selected_servant}**을(를) 성공적으로 밴했어!\n\n다른 팀장의 밴 차례를 기다리고 있어.",
                color=0x27ae60  # SUCCESS_COLOR
            )
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.send_message(
                f"❌ **{view.selected_servant}**을(를) 밴할 수 없어. 이미 밴되었거나 사용할 수 없어.",
                ephemeral=True
            )
