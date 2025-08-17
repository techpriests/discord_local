"""
Discord Integration Adapters

Adapters for Discord-specific functionality.
"""

import discord
from discord.ext import commands
from typing import Optional
from ..application.interfaces import INotificationService, IPermissionChecker
from ..domain.entities.draft import Draft


class DiscordNotificationService(INotificationService):
    """
    Discord implementation of notification service.
    
    Handles sending messages through Discord API.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def send_ephemeral_message(self, user_id: int, message: str) -> None:
        """Send ephemeral message to user (handled by interaction context)"""
        # This would typically be handled by the interaction context
        # in the presentation layer, but we provide the interface for consistency
        pass
    
    async def send_channel_message(self, channel_id: int, message: str) -> None:
        """Send message to channel"""
        try:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(message)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to send channel message: {e}")
    
    async def send_error_message(self, user_id: int, error: str) -> None:
        """Send error message to user"""
        # This would be handled by interaction context in most cases
        pass


class DiscordPermissionChecker(IPermissionChecker):
    """
    Discord implementation of permission checker.
    
    Handles Discord-specific permission checking.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def is_bot_owner(self, user_id: int) -> bool:
        """Check if user is bot owner"""
        try:
            user = self.bot.get_user(user_id)
            if user:
                return await self.bot.is_owner(user)
            return False
        except Exception:
            return False
    
    async def can_start_draft(self, user_id: int, channel_id: int) -> bool:
        """Check if user can start a draft"""
        # Basic permission check - could be enhanced with role-based permissions
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                return False
            
            if hasattr(channel, 'guild'):
                guild = channel.guild
                member = guild.get_member(user_id)
                if member:
                    # Check if member can send messages in channel
                    permissions = channel.permissions_for(member)
                    return permissions.send_messages
            
            return True
        except Exception:
            return False
    
    async def can_force_start(self, user_id: int, draft: Draft) -> bool:
        """Check if user can force start a draft"""
        # Check if user is the draft starter or bot owner
        if draft.started_by_user_id == user_id:
            return True
        
        return await self.is_bot_owner(user_id)
