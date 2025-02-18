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

    @commands.command(
        name="사용량",
        help="Gemini AI 사용량을 보여줍니다",
        brief="AI 사용량 확인",
        aliases=["usage", "사용량"],
        description="Gemini AI의 현재 사용량과 상태를 보여줍니다.\n"
        "사용법:\n"
        "• !!사용량\n"
        "• 프틸 사용량\n"
        "• pt usage"
    )
    async def usage_prefix(self, ctx: commands.Context) -> None:
        """Show Gemini AI usage statistics"""
        await self._handle_usage(ctx)

    @app_commands.command(
        name="ai_usage",
        description="Gemini AI 사용량을 보여줍니다"
    )
    async def usage_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for showing Gemini AI usage statistics"""
        await self._handle_usage(interaction)

    @command_handler()
    async def _handle_usage(self, ctx_or_interaction: CommandContext) -> None:
        """Handle usage statistics request
        
        Args:
            ctx_or_interaction: Command context or interaction
        """
        try:
            # Get formatted report
            report = self.bot.api_service.gemini.get_formatted_report()
            
            # Get health status
            health = self.bot.api_service.gemini.health_status
            
            # Create embed
            embed = discord.Embed(
                title="🤖 Gemini AI 사용량 및 상태",
                description=report,
                color=INFO_COLOR
            )
            
            # Add health status section
            status_text = []
            
            # Service status
            if not health["is_enabled"]:
                status_text.append("❌ 서비스 비활성화됨")
                if health["time_until_enable"]:
                    minutes = int(health["time_until_enable"] / 60)
                    status_text.append(f"⏳ 재활성화까지: {minutes}분")
            elif health["is_slowed_down"]:
                status_text.append("⚠️ 서비스 속도 제한 중")
                if health["time_until_slowdown_reset"]:
                    minutes = int(health["time_until_slowdown_reset"] / 60)
                    status_text.append(f"⏳ 정상화까지: {minutes}분")
            else:
                status_text.append("✅ 서비스 정상")
            
            # System metrics
            status_text.append(f"🔄 CPU 사용량: {health['cpu_usage']:.1f}%")
            status_text.append(f"💾 메모리 사용량: {health['memory_usage']:.1f}%")
            
            # Error count
            if health["error_count"] > 0:
                status_text.append(f"⚠️ 최근 오류: {health['error_count']}회")
            
            embed.add_field(
                name="시스템 상태",
                value="\n".join(status_text),
                inline=False
            )
            
            await self.send_response(ctx_or_interaction, embed=embed)
            
        except Exception as e:
            logger.error(f"Error getting usage statistics: {e}")
            raise ValueError("사용량 정보를 가져오는데 실패했습니다") from e 