"""
Servant Selection View

Discord UI view for servant selection phase with conflict detection.
Preserves legacy servant selection workflow.
"""

import discord
from discord.ext import commands
from typing import Dict, List, Optional, Any
import logging

from ...application.dto import DraftDTO
from .servant_selection_components import (
    PrivateSelectionCategoryButton,
    PrivateSelectionCharacterDropdown,
    EmptySelectionDropdown,
    ConfirmSelectionButton,
    PrivateReselectionCategoryButton,
    PrivateReselectionCharacterDropdown,
    ConfirmReselectionButton
)

logger = logging.getLogger(__name__)


class ServantSelectionView(discord.ui.View):
    """
    View for servant selection phase.
    
    Preserves legacy behavior:
    - All players including captains select servants
    - Category-based interface (8 categories)
    - Conflict detection for duplicate selections
    - Progress tracking per player
    """
    
    def __init__(self, draft_dto: DraftDTO, bot_commands):
        super().__init__(timeout=3600.0)  # 1 hour timeout (legacy)
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands
        
        # Create selection interface button and random button
        self._create_selection_buttons()
    
    def _create_selection_buttons(self):
        """Create buttons for selection interface and random selection"""
        # Main selection interface button
        selection_button = GenericSelectionInterfaceButton()
        self.add_item(selection_button)
        
        # Random selection button (legacy feature)
        random_button = RandomServantSelectionButton(self.draft_dto, self.bot_commands)
        self.add_item(random_button)


class GenericSelectionInterfaceButton(discord.ui.Button):
    """Single button for all players to open their private selection interface"""
    
    def __init__(self):
        super().__init__(
            label="🎯 내 서번트 선택하기",
            style=discord.ButtonStyle.primary,
            custom_id="open_my_selection",
            emoji="⚔️",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private selection interface for the player"""
        try:
            user_id = interaction.user.id
            view: ServantSelectionView = self.view
            
            logger.info(f"Generic selection button clicked by user {user_id}")
            
            # All players including captains can select servants in legacy system
            # (This check was incorrectly blocking captains)
            
            # Check if user is in the draft
            if user_id not in view.draft_dto.players:
                await interaction.response.send_message(
                    "드래프트에 참가하지 않았어.",
                    ephemeral=True
                )
                return
            
            # Check if user already confirmed their selection
            if user_id in view.draft_dto.confirmed_servants:
                await interaction.response.send_message(
                    f"이미 **{view.draft_dto.confirmed_servants[user_id]}**을(를) 선택했어.",
                    ephemeral=True
                )
                return
            
            # Create private selection interface
            private_view = PrivateSelectionView(view.draft_dto, view.bot_commands, user_id)
            
            # Get current player selection if any
            current_selection = None
            if user_id in view.draft_dto.players:
                player = view.draft_dto.players[user_id]
                if hasattr(player, 'selected_servant'):
                    current_selection = player['selected_servant']
            
            selection_text = f"현재 선택: {current_selection if current_selection else '없음'}"
            
            embed = discord.Embed(
                title="⚔️ 서번트 선택 - 세이버",
                description=f"**현재 카테고리: 세이버**\n{selection_text}",
                color=0x3498db  # INFO_COLOR
            )
            
            # Show characters in current category with status
            chars_in_category = view.draft_dto.servant_categories["세이버"]
            char_list = []
            for char in chars_in_category:
                if char in view.draft_dto.banned_servants:
                    char_list.append(f"❌ {char}")
                else:
                    char_list.append(f"• {char}")
            
            embed.add_field(name="세이버 서번트 목록", value="\n".join(char_list), inline=False)
            
            await interaction.response.send_message(embed=embed, view=private_view, ephemeral=True)
        
        except Exception as e:
            logger.error(f"Failed to open private selection interface: {e}")
            await interaction.response.send_message(
                "선택 인터페이스를 열 수 없어. 다시 시도해줘.",
                ephemeral=True
            )


class RandomServantSelectionButton(discord.ui.Button):
    """Button for random servant selection (legacy feature)"""
    
    def __init__(self, draft_dto: DraftDTO, bot_commands):
        super().__init__(
            label="🎲 랜덤 서번트",
            style=discord.ButtonStyle.secondary,
            custom_id="random_servant_selection",
            emoji="🎯",
            row=0
        )
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle random servant selection"""
        try:
            user_id = interaction.user.id
            
            logger.info(f"Random servant selection clicked by user {user_id}")
            
            # Check if user is in the draft
            if user_id not in self.draft_dto.players:
                await interaction.response.send_message(
                    "드래프트에 참가하지 않았어.",
                    ephemeral=True
                )
                return
            
            # Check if user already confirmed their selection
            if user_id in self.draft_dto.confirmed_servants:
                await interaction.response.send_message(
                    f"이미 **{self.draft_dto.confirmed_servants[user_id]}**을(를) 선택했어.",
                    ephemeral=True
                )
                return
            
            # Get all available servants (excluding banned)
            all_servants = set()
            for servants in self.draft_dto.servant_categories.values():
                all_servants.update(servants)
            
            available_servants = all_servants - self.draft_dto.banned_servants
            
            # Remove already confirmed servants
            if hasattr(self.draft_dto, 'confirmed_servants'):
                available_servants = available_servants - set(self.draft_dto.confirmed_servants.values())
            
            # Remove reselection auto-bans if in reselection phase
            if hasattr(self.draft_dto, 'reselection_auto_bans'):
                available_servants = available_servants - set(self.draft_dto.reselection_auto_bans)
            
            available_servants_list = list(available_servants)
            
            if not available_servants_list:
                await interaction.response.send_message(
                    "랜덤으로 선택할 수 있는 서번트가 없어.",
                    ephemeral=True
                )
                return
            
            # Select random servant
            import random
            random_servant = random.choice(available_servants_list)
            
            # Apply the selection through bot commands
            success = await self.bot_commands.apply_servant_selection(
                self.draft_dto.channel_id,
                user_id,
                random_servant
            )
            
            if success:
                await interaction.response.send_message(
                    f"🎲 **{random_servant}**을(를) 랜덤으로 선택했어!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{random_servant}**을(를) 선택할 수 없어. 다시 시도해줘.",
                    ephemeral=True
                )
        
        except Exception as e:
            logger.error(f"Random servant selection failed: {e}")
            await interaction.response.send_message(
                "랜덤 선택 중 오류가 발생했어.",
                ephemeral=True
            )


class PrivateSelectionView(discord.ui.View):
    """
    Private selection interface with category-based navigation.
    
    Mimics the legacy EphemeralSelectionView with full category support.
    """
    
    def __init__(self, draft_dto: DraftDTO, bot_commands, user_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands
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
            button = PrivateSelectionCategoryButton(category, i, self.user_id)
            self.add_item(button)
    
    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, (PrivateSelectionCharacterDropdown, EmptySelectionDropdown)):
                self.remove_item(item)
        
        # Get available characters for current category (exclude banned)
        excluded_servants = self.draft_dto.banned_servants.copy()
        
        available_in_category = [
            char for char in self.draft_dto.servant_categories[self.current_category]
            if char not in excluded_servants
        ]
        
        # Check if category has any available characters
        if not available_in_category:
            # Create a disabled dropdown showing no characters available
            dropdown = EmptySelectionDropdown(self.current_category)
            self.add_item(dropdown)
        else:
            # Create normal dropdown with available characters
            dropdown = PrivateSelectionCharacterDropdown(
                self.draft_dto, self.bot_commands, available_in_category, 
                self.current_category, self.user_id
            )
            self.add_item(dropdown)
    
    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmSelectionButton(self.user_id)
        self.add_item(button)
    
    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        selection_text = f"현재 선택: {self.selected_servant if self.selected_servant else '없음'}"
        
        embed = discord.Embed(
            title=f"⚔️ 서번트 선택 - {new_category}",
            description=f"**현재 카테고리: {new_category}**\n{selection_text}",
            color=0x3498db  # INFO_COLOR
        )
        
        # Show characters in current category with status
        chars_in_category = self.draft_dto.servant_categories[new_category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft_dto.banned_servants:
                char_list.append(f"❌ {char}")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{new_category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


class ServantReselectionView(discord.ui.View):
    """
    View for servant reselection phase (conflict resolution).
    
    Similar to ServantSelectionView but for conflicted players only.
    """
    
    def __init__(self, draft_dto: DraftDTO, bot_commands):
        super().__init__(timeout=3600.0)  # 1 hour timeout (legacy)
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands
        
        # Create reselection interface button and random button
        self._create_reselection_buttons()
    
    def _create_reselection_buttons(self):
        """Create buttons for reselection interface and random selection"""
        # Main reselection interface button
        reselection_button = GenericReselectionInterfaceButton()
        self.add_item(reselection_button)
        
        # Random reselection button (legacy feature)
        random_button = RandomServantReselectionButton(self.draft_dto, self.bot_commands)
        self.add_item(random_button)


class GenericReselectionInterfaceButton(discord.ui.Button):
    """Button for opening private reselection interface during conflicts"""
    
    def __init__(self):
        super().__init__(
            label="🔄 내 서번트 재선택하기",
            style=discord.ButtonStyle.danger,
            custom_id="open_my_reselection",
            emoji="⚔️",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private reselection interface for conflicted players"""
        try:
            user_id = interaction.user.id
            view: ServantReselectionView = self.view
            
            # Check if user needs to reselect
            conflicted_users = []
            for servant, user_ids in view.draft_dto.conflicted_servants.items():
                conflicted_users.extend(user_ids)
            
            if user_id not in conflicted_users:
                await interaction.response.send_message(
                    "재선택할 필요가 없어.", ephemeral=True
                )
                return
            
            # Create private reselection interface 
            private_view = PrivateReselectionView(view.draft_dto, view.bot_commands, user_id)
            
            embed = discord.Embed(
                title="🔄 서번트 재선택 - 세이버",
                description="**현재 카테고리: 세이버**\n중복 선택으로 인해 재선택이 필요해.",
                color=0xf39c12  # WARNING_COLOR
            )
            
            # Show characters in current category with status
            chars_in_category = view.draft_dto.servant_categories["세이버"]
            char_list = []
            for char in chars_in_category:
                if char in view.draft_dto.banned_servants:
                    char_list.append(f"❌ {char}")
                elif char in view.draft_dto.confirmed_servants.values():
                    char_list.append(f"🔒 {char} (확정됨)")
                else:
                    char_list.append(f"• {char}")
            
            embed.add_field(name="세이버 서번트 목록", value="\n".join(char_list), inline=False)
            
            await interaction.response.send_message(embed=embed, view=private_view, ephemeral=True)
        
        except Exception as e:
            logger.error(f"Failed to open private reselection interface: {e}")
            await interaction.response.send_message(
                "재선택 인터페이스를 열 수 없어. 다시 시도해줘.", ephemeral=True
            )


class RandomServantReselectionButton(discord.ui.Button):
    """Button for random servant reselection during conflicts (legacy feature)"""
    
    def __init__(self, draft_dto: DraftDTO, bot_commands):
        super().__init__(
            label="🎲 랜덤 재선택",
            style=discord.ButtonStyle.secondary,
            custom_id="random_servant_reselection",
            emoji="🔄",
            row=0
        )
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle random servant reselection"""
        try:
            user_id = interaction.user.id
            
            logger.info(f"Random servant reselection clicked by user {user_id}")
            
            # Check if user needs to reselect
            conflicted_users = []
            for servant, user_ids in self.draft_dto.conflicted_servants.items():
                conflicted_users.extend(user_ids)
            
            if user_id not in conflicted_users:
                await interaction.response.send_message(
                    "재선택할 필요가 없어.", ephemeral=True
                )
                return
            
            # Get all available servants (excluding banned, confirmed, and auto-banned)
            all_servants = set()
            for servants in self.draft_dto.servant_categories.values():
                all_servants.update(servants)
            
            # Remove banned servants
            available_servants = all_servants - self.draft_dto.banned_servants
            
            # Remove already confirmed servants
            available_servants = available_servants - set(self.draft_dto.confirmed_servants.values())
            
            # Remove reselection auto-bans
            if hasattr(self.draft_dto, 'reselection_auto_bans'):
                available_servants = available_servants - set(self.draft_dto.reselection_auto_bans)
            
            available_servants_list = list(available_servants)
            
            if not available_servants_list:
                await interaction.response.send_message(
                    "랜덤으로 재선택할 수 있는 서번트가 없어.",
                    ephemeral=True
                )
                return
            
            # Select random servant
            import random
            random_servant = random.choice(available_servants_list)
            
            # Apply the reselection through bot commands (same as selection)
            success = await self.bot_commands.apply_servant_selection(
                self.draft_dto.channel_id,
                user_id,
                random_servant
            )
            
            if success:
                await interaction.response.send_message(
                    f"🎲 **{random_servant}**을(를) 랜덤으로 재선택했어!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{random_servant}**을(를) 재선택할 수 없어. 다시 시도해줘.",
                    ephemeral=True
                )
        
        except Exception as e:
            logger.error(f"Random servant reselection failed: {e}")
            await interaction.response.send_message(
                "랜덤 재선택 중 오류가 발생했어.",
                ephemeral=True
            )


class PrivateReselectionView(discord.ui.View):
    """Private reselection interface with category-based navigation for conflicts"""
    
    def __init__(self, draft_dto: DraftDTO, bot_commands, user_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft_dto = draft_dto
        self.bot_commands = bot_commands
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
            button = PrivateReselectionCategoryButton(category, i, self.user_id)
            self.add_item(button)
    
    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, (PrivateReselectionCharacterDropdown, EmptySelectionDropdown)):
                self.remove_item(item)
        
        # Get available characters for current category (exclude banned + confirmed)
        excluded_servants = self.draft_dto.banned_servants.copy()
        excluded_servants.update(self.draft_dto.confirmed_servants.values())
        
        # Also exclude reselection auto-bans if they exist
        if hasattr(self.draft_dto, 'reselection_auto_bans'):
            excluded_servants.update(self.draft_dto.reselection_auto_bans)
        
        available_in_category = [
            char for char in self.draft_dto.servant_categories[self.current_category]
            if char not in excluded_servants
        ]
        
        # Check if category has any available characters
        if not available_in_category:
            # Create a disabled dropdown showing no characters available
            dropdown = EmptySelectionDropdown(self.current_category)
            self.add_item(dropdown)
        else:
            # Create normal dropdown with available characters
            dropdown = PrivateReselectionCharacterDropdown(
                self.draft_dto, self.bot_commands, available_in_category, 
                self.current_category, self.user_id
            )
            self.add_item(dropdown)
    
    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmReselectionButton(self.user_id)
        self.add_item(button)
    
    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        selection_text = f"현재 선택: {self.selected_servant if self.selected_servant else '없음'}"
        
        embed = discord.Embed(
            title=f"🔄 서번트 재선택 - {new_category}",
            description=f"**현재 카테고리: {new_category}**\n{selection_text}",
            color=0xf39c12  # WARNING_COLOR
        )
        
        # Show characters in current category with status
        chars_in_category = self.draft_dto.servant_categories[new_category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft_dto.banned_servants:
                char_list.append(f"❌ {char}")
            elif char in self.draft_dto.confirmed_servants.values():
                char_list.append(f"🔒 {char} (확정됨)")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{new_category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


def create_servant_selection_embed(draft_dto: DraftDTO) -> discord.Embed:
    """Create embed for servant selection phase"""
    embed = discord.Embed(
        title="🎭 서번트 선택",
        description="**👇 아래 버튼을 눌러서 자신의 서번트를 선택해!**\n• 개인 선택창이 열려 (나만 볼 수 있음)\n• 선택 내용은 모든 플레이어가 완료된 후에 공개될거야\n⏰ **제한 시간: 1분 30초**",
        color=0x3498db  # INFO_COLOR
    )
    
    # Show selection progress
    non_captain_players = [
        p for p in draft_dto.players.values() 
        if p['user_id'] not in draft_dto.captains
    ]
    
    selected_count = len([
        p for p in non_captain_players 
        if hasattr(p, 'selected_servant') and p.get('selected_servant')
    ])
    
    embed.add_field(
        name="진행 상황",
        value=f"{selected_count}/{len(non_captain_players)} 플레이어가 선택 완료",
        inline=False
    )
    
    # Show banned servants
    if draft_dto.banned_servants:
        banned_list = ", ".join(list(draft_dto.banned_servants)[:10])  # Show first 10
        if len(draft_dto.banned_servants) > 10:
            banned_list += f" (총 {len(draft_dto.banned_servants)}개)"
        
        embed.add_field(
            name="❌ 밴된 서번트",
            value=banned_list,
            inline=False
        )
    
    return embed


def create_servant_reselection_embed(draft_dto: DraftDTO) -> discord.Embed:
    """Create embed for servant reselection phase"""
    embed = discord.Embed(
        title="⚔️ 서번트 선택 결과 - 중복이 있어",
        description="중복 선택된 서번트가 있네. 주사위로 결정하자.\n일부 서번트는 확정되었고, 중복된 플레이어들은 재선택해야 해.\n⏰ **재선택 제한 시간: 1분 30초**",
        color=0xf39c12  # WARNING_COLOR
    )
    
    # Show conflicted servants
    if draft_dto.conflicted_servants:
        conflict_text = ""
        for servant, user_ids in draft_dto.conflicted_servants.items():
            user_names = []
            for user_id in user_ids:
                if user_id in draft_dto.players:
                    user_names.append(draft_dto.players[user_id]['username'])
            
            if user_names:
                conflict_text += f"**{servant}**: {', '.join(user_names)}\n"
        
        if conflict_text:
            embed.add_field(
                name="충돌된 서번트",
                value=conflict_text.strip(),
                inline=False
            )
    
    # Show auto-banned cloaking servants
    if hasattr(draft_dto, 'reselection_auto_bans') and draft_dto.reselection_auto_bans:
        auto_ban_text = ", ".join(draft_dto.reselection_auto_bans)
        embed.add_field(
            name="🚫 자동 밴 (은신 서번트)",
            value=f"탐지 서번트가 없어서 자동으로 밴됨: {auto_ban_text}",
            inline=False
        )
    
    return embed
