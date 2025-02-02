import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

"""Base command class providing common functionality for all command types."""

class BaseCommands(commands.Cog):
    """Base class for all command categories providing common functionality."""

    async def send_response(
        self, ctx_or_interaction, message: str = None, embed: discord.Embed = None
    ):
        """Unified method to send responses"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(content=message, embed=embed)
            else:
                await ctx_or_interaction.response.send_message(content=message, embed=embed)
        else:
            await ctx_or_interaction.send(content=message, embed=embed)

    async def _send_response(
        self, ctx_or_interaction, message: str = None, embed: discord.Embed = None
    ):
        """Send response to command

        Args:
            ctx_or_interaction: Command context or interaction
            message: Optional text message
            embed: Optional embed message
        """
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                await self._send_interaction_response(ctx_or_interaction, message, embed)
            else:
                await self._send_context_response(ctx_or_interaction, message, embed)

        except Exception as e:
            logger.error(f"Error sending response: {e}")
            raise ValueError("응답을 보내는데 실패했습니다") from e

    async def _send_interaction_response(
        self, interaction: discord.Interaction, message: str = None, embed: discord.Embed = None
    ):
        """Send response to slash command interaction

        Args:
            interaction: Slash command interaction
            message: Optional text message
            embed: Optional embed message
        """
        if interaction.response.is_done():
            await self._send_followup_response(interaction, message, embed)
        else:
            await self._send_initial_response(interaction, message, embed)

    async def _send_followup_response(
        self, interaction: discord.Interaction, message: str = None, embed: discord.Embed = None
    ):
        """Send followup response to interaction

        Args:
            interaction: Slash command interaction
            message: Optional text message
            embed: Optional embed message
        """
        await interaction.followup.send(content=message, embed=embed, ephemeral=True)

    async def _send_initial_response(
        self, interaction: discord.Interaction, message: str = None, embed: discord.Embed = None
    ):
        """Send initial response to interaction

        Args:
            interaction: Slash command interaction
            message: Optional text message
            embed: Optional embed message
        """
        await interaction.response.send_message(content=message, embed=embed, ephemeral=True)

    async def _send_context_response(
        self, ctx: commands.Context, message: str = None, embed: discord.Embed = None
    ):
        """Send response to command context

        Args:
            ctx: Command context
            message: Optional text message
            embed: Optional embed message
        """
        await ctx.send(content=message, embed=embed)
