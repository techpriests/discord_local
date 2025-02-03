import logging
from typing import Optional, Union, Any, Dict, cast

import discord
from discord.ext import commands
from discord.ext.commands import Context

from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR

logger = logging.getLogger(__name__)

"""Base command class providing common functionality for all command types."""

class BaseCommands(commands.Cog):
    """Base class for all command categories providing common functionality."""

    async def send_response(
        self,
        ctx_or_interaction: CommandContext,
        message: Optional[str] = None,
        *,
        embed: Optional[discord.Embed] = None,
        ephemeral: bool = False
    ) -> None:
        """Send response to command
        
        Args:
            ctx_or_interaction: Command context or interaction
            message: Optional text message
            embed: Optional embed message
            ephemeral: Whether the response should be ephemeral (only visible to command user)

        Returns:
            None

        Raises:
            discord.Forbidden: If bot lacks permission to send message
            discord.HTTPException: If sending message fails
        """
        try:
            # Create default embed with description if none provided
            if not embed:
                embed = discord.Embed(description=message or "No message provided")
                message = None  # Clear message since we moved it to embed description

            # Ensure embed has a description
            if not embed.description:
                embed.description = message or "No message provided"
                message = None  # Clear message since we moved it to embed description

            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(
                        content=message,  # This might be None now
                        embed=embed,
                        ephemeral=ephemeral
                    )
                else:
                    await ctx_or_interaction.response.send_message(
                        content=message,  # This might be None now
                        embed=embed,
                        ephemeral=ephemeral
                    )
            else:
                await ctx_or_interaction.send(
                    content=message,  # This might be None now
                    embed=embed
                )
        except Exception as e:
            logger.error(f"Error sending response: {e}")
            raise

    async def send_error(
        self,
        ctx_or_interaction: CommandContext,
        error_message: str,
        *,
        ephemeral: bool = True
    ) -> None:
        """Send error message with standard formatting
        
        Args:
            ctx_or_interaction: Command context or interaction
            error_message: Error message to display
            ephemeral: Whether the response should be ephemeral
        """
        embed = discord.Embed(
            title="❌ 오류",
            description=error_message,
            color=ERROR_COLOR
        )
        await self.send_response(
            ctx_or_interaction, 
            embed=embed, 
            ephemeral=ephemeral
        )

    async def send_success(
        self,
        ctx_or_interaction: CommandContext,
        message: str,
        *,
        ephemeral: bool = False
    ) -> None:
        """Send success message with standard formatting
        
        Args:
            ctx_or_interaction: Command context or interaction
            message: Success message to display
            ephemeral: Whether the response should be ephemeral
        """
        embed = discord.Embed(
            title="✅ 성공",
            description=message,
            color=INFO_COLOR
        )
        await self.send_response(
            ctx_or_interaction, 
            embed=embed, 
            ephemeral=ephemeral
        )

    def get_user_name(self, ctx_or_interaction: CommandContext) -> str:
        """Get username from context or interaction
        
        Args:
            ctx_or_interaction: Command context or interaction

        Returns:
            str: Username (server display name if in a guild, otherwise Discord username)
        """
        if isinstance(ctx_or_interaction, discord.Interaction):
            # For interactions, check if we're in a guild and get the member's display name
            if ctx_or_interaction.guild:
                member = ctx_or_interaction.guild.get_member(ctx_or_interaction.user.id)
                if member:
                    return member.display_name
            return ctx_or_interaction.user.name
        else:
            # For context, use author's display name
            return ctx_or_interaction.author.display_name

    def get_user_id(self, ctx_or_interaction: CommandContext) -> int:
        """Get user ID from context or interaction
        
        Args:
            ctx_or_interaction: Command context or interaction

        Returns:
            int: User ID
        """
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.user.id
        return ctx_or_interaction.author.id

    def get_channel_id(self, ctx_or_interaction: CommandContext) -> int:
        """Get channel ID from context or interaction
        
        Args:
            ctx_or_interaction: Command context or interaction

        Returns:
            int: Channel ID
        """
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.channel_id
        return ctx_or_interaction.channel.id

    def get_guild_id(self, ctx_or_interaction: CommandContext) -> Optional[int]:
        """Get guild ID from context or interaction
        
        Args:
            ctx_or_interaction: Command context or interaction

        Returns:
            Optional[int]: Guild ID if in a guild, None otherwise
        """
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.guild_id
        return ctx_or_interaction.guild.id if ctx_or_interaction.guild else None
