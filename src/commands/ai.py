import logging
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from src.utils.decorators import command_handler
from .base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR

logger = logging.getLogger(__name__)


class AICommands(BaseCommands):
    """AI-related commands including Gemini integration"""

    def __init__(self) -> None:
        """Initialize AI commands"""
        super().__init__()

    @commands.command(
        name="대화",
        help="Gemini AI와 대화를 나눕니다",
        brief="AI와 대화하기",
        aliases=["chat", "채팅"],
        description="Gemini AI와 대화를 나누는 명령어입니다.\n"
        "사용법:\n"
        "- !!대화 [메시지]\n"
        "- 프틸 대화 [메시지]\n"
        "- pt 대화 [메시지]\n"
        "예시:\n"
        "- !!대화 안녕하세요\n"
        "- 프틸 대화 오늘 날씨 어때요?\n"
        "- pt 대화 지금 기분이 어때?",
    )
    async def chat(self, ctx: commands.Context, *, message: str) -> None:
        """Chat with Gemini AI
        
        Args:
            ctx: Command context
            message: Message to send to Gemini
        """
        try:
            # Send typing indicator while processing
            async with ctx.typing():
                # Get response from Gemini
                response = await self.bot.api_service.gemini.chat(message, ctx.author.id)
                
                # Create embed for response
                embed = discord.Embed(
                    title="Gemini AI 응답",
                    description=response,
                    color=INFO_COLOR
                )
                embed.set_footer(text="Powered by Google Gemini")
                
                await ctx.send(embed=embed)
                
        except ValueError as e:
            # Handle API errors
            error_embed = discord.Embed(
                title="오류",
                description=str(e),
                color=ERROR_COLOR
            )
            await ctx.send(embed=error_embed)
        except Exception as e:
            logger.error(f"Error in chat command: {e}")
            raise ValueError("대화 처리에 실패했습니다") from e

    @app_commands.command(
        name="chat",
        description="Gemini AI와 대화를 나눕니다"
    )
    async def chat_slash(
        self,
        interaction: discord.Interaction,
        message: str
    ) -> None:
        """Slash command for chatting with Gemini AI"""
        await self._handle_chat(interaction, message)

    @command_handler()
    async def _handle_chat(
        self,
        ctx_or_interaction: CommandContext,
        message: str
    ) -> None:
        """Handle chat command
        
        Args:
            ctx_or_interaction: Command context or interaction
            message: Message to send to Gemini
        """
        try:
            # Get user ID based on context type
            user_id = (
                ctx_or_interaction.author.id 
                if isinstance(ctx_or_interaction, commands.Context)
                else ctx_or_interaction.user.id
            )
            
            # Get response from Gemini
            response = await self.bot.api_service.gemini.chat(message, user_id)
            
            # Create embed for response
            embed = discord.Embed(
                title="Gemini AI 응답",
                description=response,
                color=INFO_COLOR
            )
            embed.set_footer(text="Powered by Google Gemini")
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)
                
        except ValueError as e:
            # Handle API errors
            error_embed = discord.Embed(
                title="오류",
                description=str(e),
                color=ERROR_COLOR
            )
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=error_embed)
            else:
                await ctx_or_interaction.send(embed=error_embed)
        except Exception as e:
            logger.error(f"Error in chat command: {e}")
            raise ValueError("대화 처리에 실패했습니다") from e 