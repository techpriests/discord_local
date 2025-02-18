import logging
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from src.utils.decorators import command_handler
from .base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR
from src.services.api.service import APIService

logger = logging.getLogger(__name__)


class AICommands(BaseCommands):
    """AI-related commands including Gemini integration"""

    def __init__(self) -> None:
        """Initialize AI commands"""
        super().__init__()
        self._api_service = None

    @property
    def api_service(self) -> APIService:
        """Get API service instance
        
        Returns:
            APIService: API service instance
            
        Raises:
            ValueError: If API service is not initialized
        """
        if not self.bot or not self.bot.api_service:
            raise ValueError("Gemini API not initialized")
        return self.bot.api_service

    @commands.command(
        name="대화",
        help="프틸롭시스와 대화를 나눕니다",
        brief="프틸롭시스와 대화하기",
        aliases=["chat", "채팅"],
        description="프틸롭시스와 대화를 나누는 명령어입니다.\n"
        "대화는 30분간 지속되며, 이전 대화 내용을 기억합니다.\n\n"
        "사용법:\n"
        "• !!대화 [메시지] - 프틸롭시스와 대화를 시작합니다\n"
        "• !!대화종료 - 현재 진행 중인 대화를 종료합니다\n"
        "• !!사용량 - 시스템 상태를 확인합니다\n\n"
        "제한사항:\n"
        "• 분당 최대 4회 요청 가능\n"
        "• 요청 간 5초 대기 시간\n"
        "• 대화는 30분 후 자동 종료\n\n"
        "예시:\n"
        "• !!대화 안녕하세요\n"
        "• !!대화 로도스 아일랜드에 대해 설명해줘\n"
        "• !!대화 오리지늄이 뭐야?"
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
                response = await self.api_service.gemini.chat(message, ctx.author.id)
                
                # Create embed for response
                embed = discord.Embed(
                    description=response,
                    color=INFO_COLOR
                )
                
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
            logger.error(f"Error in chat command: {e}", exc_info=True)
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
            response = await self.api_service.gemini.chat(message, user_id)
            
            # Create embed for response
            embed = discord.Embed(
                description=response,
                color=INFO_COLOR
            )
            
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
            logger.error(f"Error in chat command: {e}", exc_info=True)
            raise ValueError("대화 처리에 실패했습니다") from e

    @commands.command(
        name="사용량",
        help="시스템 상태와 사용량을 확인합니다",
        brief="시스템 상태 확인",
        aliases=["usage", "상태"],
        description="프틸롭시스의 현재 시스템 상태와 사용량을 보여줍니다.\n"
        "토큰 사용량, CPU/메모리 사용량, 오류 상태 등을 확인할 수 있습니다.\n\n"
        "사용법:\n"
        "• !!사용량 - 전체 시스템 상태 확인\n"
        "• 프틸 사용량\n"
        "• pt usage\n\n"
        "표시 정보:\n"
        "• 현재 분당 요청 수\n"
        "• 일간 토큰 사용량\n"
        "• CPU/메모리 사용량\n"
        "• 시스템 상태 및 오류"
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
            report = self.api_service.gemini.get_formatted_report()
            
            # Get health status
            health = self.api_service.gemini.health_status
            
            # Create embed
            embed = discord.Embed(
                title="🤖 시스템 상태",
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

    @commands.command(
        name="대화종료",
        help="현재 진행 중인 대화 세션을 종료합니다",
        brief="대화 세션 종료하기",
        aliases=["endchat", "세션종료"],
        description="현재 진행 중인 프틸롭시스와의 대화를 종료합니다.\n"
        "대화가 종료되면 이전 대화 내용은 더 이상 기억되지 않습니다.\n\n"
        "사용법:\n"
        "• !!대화종료 - 현재 대화 세션을 즉시 종료\n"
        "• 프틸 대화종료\n"
        "• pt endchat\n\n"
        "참고:\n"
        "• 대화는 30분 동안 활동이 없으면 자동으로 종료됩니다\n"
        "• 새로운 대화는 !!대화 명령어로 언제든 시작할 수 있습니다"
    )
    async def end_chat(self, ctx: commands.Context) -> None:
        """End current chat session"""
        try:
            if self.api_service.gemini.end_chat_session(ctx.author.id):
                embed = discord.Embed(
                    title="✅ 대화 세션 종료",
                    description="대화 세션이 종료되었습니다.\n새로운 대화를 시작하실 수 있습니다.",
                    color=INFO_COLOR
                )
            else:
                embed = discord.Embed(
                    title="ℹ️ 알림",
                    description="진행 중인 대화 세션이 없습니다.",
                    color=INFO_COLOR
                )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in end_chat command: {e}")
            raise ValueError("대화 세션 종료에 실패했습니다") from e 