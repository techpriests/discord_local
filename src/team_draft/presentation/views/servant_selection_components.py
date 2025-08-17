"""
Servant Selection UI Components

Additional UI components for the category-based servant selection interface.
These components restore the legacy behavior that was missing from the refactored system.
"""

import discord
import logging
from typing import List
from ...application.dto import DraftDTO

logger = logging.getLogger(__name__)


# ===========================
# Private Selection Interface Components
# ===========================

class PrivateSelectionCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private selection interface"""
    
    def __init__(self, category: str, index: int, user_id: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_selection_category_{category}_{user_id}",
            row=index // 4
        )
        self.category = category
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        from .servant_selection import PrivateSelectionView
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 선택 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        await view.update_category(self.category, interaction)


class PrivateSelectionCharacterDropdown(discord.ui.Select):
    """Dropdown for character selection within a category"""
    
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
            placeholder=f"{category}에서 선택해줘...",
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
        """Handle character selection"""
        from .servant_selection import PrivateSelectionView
        user_id = interaction.user.id
        view: PrivateSelectionView = self.view
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 선택 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        servant_name = self.values[0]
        view.selected_servant = servant_name
        
        # Update the interface to show the selection
        selection_text = f"현재 선택: {servant_name}"
        
        embed = discord.Embed(
            title=f"⚔️ 서번트 선택 - {self.category}",
            description=f"**현재 카테고리: {self.category}**\n{selection_text}\n\n✅ **{servant_name}**을(를) 임시 선택했어. 확정하려면 확정 버튼을 눌러줘.",
            color=0x27ae60  # SUCCESS_COLOR
        )
        
        # Show characters in current category with selection highlighted
        chars_in_category = self.draft_dto.servant_categories[self.category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft_dto.banned_servants:
                char_list.append(f"❌ {char}")
            elif char == servant_name:
                char_list.append(f"✅ **{char}** (선택됨)")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{self.category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=view)


class EmptySelectionDropdown(discord.ui.Select):
    """Disabled dropdown for categories with no available characters"""
    
    def __init__(self, category: str):
        super().__init__(
            placeholder=f"{category}에 선택 가능한 서번트가 없어",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="선택 불가",
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


class ConfirmSelectionButton(discord.ui.Button):
    """Button to confirm servant selection"""
    
    def __init__(self, user_id: int):
        super().__init__(
            label="✅ 선택 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_selection_{user_id}",
            row=3
        )
        self.user_id = user_id
    
    async def callback(self, interaction: discord.Interaction):
        """Handle selection confirmation"""
        from .servant_selection import PrivateSelectionView
        user_id = interaction.user.id
        view: PrivateSelectionView = self.view
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 선택 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        if not view.selected_servant:
            await interaction.response.send_message(
                "먼저 서번트를 선택해줘.", ephemeral=True
            )
            return
        
        # Apply the selection through the draft system with logging
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"UI servant selection: {user_id} confirming selection of {view.selected_servant}")
        
        from ...presentation.discord_integration import get_integration
        integration = get_integration()
        if integration:
            success = await integration.apply_servant_selection(
                view.draft_dto.channel_id,
                user_id,
                view.selected_servant
            )
            if success:
                logger.info(f"UI servant selection: Successfully confirmed {view.selected_servant} for user {user_id}")
            else:
                logger.warning(f"UI servant selection: Failed to confirm {view.selected_servant} for user {user_id}")
        else:
            # Fall back to presenter if available
            success = False  # presenter doesn't have direct apply method
            logger.error(f"UI servant selection: No integration available to apply selection")
        
        if success:
            embed = discord.Embed(
                title="✅ 선택 완료!",
                description=f"**{view.selected_servant}**을(를) 성공적으로 선택했어!\n\n다른 플레이어들의 선택을 기다리고 있어.",
                color=0x27ae60  # SUCCESS_COLOR
            )
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.send_message(
                f"❌ **{view.selected_servant}**을(를) 선택할 수 없어. 이미 밴되었거나 사용할 수 없어.",
                ephemeral=True
            )


# ===========================
# Reselection Interface Components  
# ===========================

class PrivateReselectionCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private reselection interface"""
    
    def __init__(self, category: str, index: int, user_id: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_reselection_category_{category}_{user_id}",
            row=index // 4
        )
        self.category = category
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        from .servant_selection import PrivateReselectionView
        view: PrivateReselectionView = self.view
        user_id = interaction.user.id
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 선택 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        await view.update_category(self.category, interaction)


class PrivateReselectionCharacterDropdown(discord.ui.Select):
    """Dropdown for character reselection within a category"""
    
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
            placeholder=f"{category}에서 재선택해줘...",
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
        """Handle character reselection"""
        from .servant_selection import PrivateReselectionView
        user_id = interaction.user.id
        view: PrivateReselectionView = self.view
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 선택 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        servant_name = self.values[0]
        view.selected_servant = servant_name
        
        # Update the interface to show the selection
        selection_text = f"현재 선택: {servant_name}"
        
        embed = discord.Embed(
            title=f"🔄 서번트 재선택 - {self.category}",
            description=f"**현재 카테고리: {self.category}**\n{selection_text}\n\n✅ **{servant_name}**을(를) 임시 선택했어. 확정하려면 확정 버튼을 눌러줘.",
            color=0x27ae60  # SUCCESS_COLOR
        )
        
        # Show characters in current category with selection highlighted
        chars_in_category = self.draft_dto.servant_categories[self.category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft_dto.banned_servants:
                char_list.append(f"❌ {char}")
            elif char in self.draft_dto.confirmed_servants.values():
                char_list.append(f"🔒 {char} (확정됨)")
            elif char == servant_name:
                char_list.append(f"✅ **{char}** (선택됨)")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{self.category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=view)
        
        # Trigger real-time progress update for temporary reselection (legacy behavior)
        try:
            from ...presentation.discord_integration import get_integration
            integration = get_integration()
            if integration and hasattr(integration, 'presenter'):
                updated_draft = await integration.presenter.draft_service.get_draft_status(view.draft_dto.channel_id)
                if updated_draft:
                    await integration.presenter.update_servant_reselection_progress(updated_draft)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to trigger reselection progress update on temp selection: {e}")


class ConfirmReselectionButton(discord.ui.Button):
    """Button to confirm servant reselection"""
    
    def __init__(self, user_id: int):
        super().__init__(
            label="✅ 재선택 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_reselection_{user_id}",
            row=3
        )
        self.user_id = user_id
    
    async def callback(self, interaction: discord.Interaction):
        """Handle reselection confirmation"""
        from .servant_selection import PrivateReselectionView
        user_id = interaction.user.id
        view: PrivateReselectionView = self.view
        
        if user_id != self.user_id:
            await interaction.response.send_message(
                "다른 사람의 선택 인터페이스는 사용할 수 없어.", ephemeral=True
            )
            return
        
        if not view.selected_servant:
            await interaction.response.send_message(
                "먼저 서번트를 선택해줘.", ephemeral=True
            )
            return
        
        # Apply the reselection through the draft system with logging
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"UI servant reselection: {user_id} confirming reselection of {view.selected_servant}")
        
        from ...presentation.discord_integration import get_integration
        integration = get_integration()
        if integration:
            success = await integration.apply_servant_selection(
                view.draft_dto.channel_id,
                user_id,
                view.selected_servant
            )
            if success:
                logger.info(f"UI servant reselection: Successfully confirmed {view.selected_servant} for user {user_id}")
            else:
                logger.warning(f"UI servant reselection: Failed to confirm {view.selected_servant} for user {user_id}")
        else:
            # Fall back to presenter if available  
            success = False  # presenter doesn't have direct apply method
            logger.error(f"UI servant reselection: No integration available to apply reselection")
        
        if success:
            embed = discord.Embed(
                title="✅ 재선택 완료!",
                description=f"**{view.selected_servant}**으로 성공적으로 재선택했어!\n\n다른 플레이어들의 선택을 기다리고 있어.",
                color=0x27ae60  # SUCCESS_COLOR
            )
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Trigger real-time progress update for reselection (legacy behavior)
            try:
                from ...presentation.discord_integration import get_integration
                integration = get_integration()
                if integration and hasattr(integration, 'presenter'):
                    updated_draft = await integration.presenter.draft_service.get_draft_status(view.draft_dto.channel_id)
                    if updated_draft:
                        await integration.presenter.update_servant_reselection_progress(updated_draft)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to trigger reselection progress update: {e}")
        else:
            await interaction.response.send_message(
                f"❌ **{view.selected_servant}**을(를) 선택할 수 없어. 이미 밴되었거나 사용할 수 없어.",
                ephemeral=True
            )
