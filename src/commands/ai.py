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
            raise ValueError("API 서비스가 초기화되지 않았습니다")
        return self.bot.api_service

    async def _check_gemini_state(self) -> bool:
        """Check if Gemini API is available and ready for use.
        
        Returns:
            bool: True if Gemini API is available
            
        Raises:
            ValueError: If Gemini API is not available or not initialized
        """
        try:
            logger.info("Checking Gemini API state...")
            
            # Check API service initialization
            logger.info(f"API service initialized: {self.api_service.initialized}")
            if not self.api_service.initialized:
                raise ValueError("API 서비스가 초기화되지 않았습니다")
            
            # Check Gemini API instance
            logger.info(f"Gemini API instance present: {self.api_service.gemini_api is not None}")
            if not self.api_service.gemini_api:
                raise ValueError("AI 기능이 비활성화되어 있습니다. 관리자에게 문의하세요.")
            
            # Check Gemini API state
            api_states = self.api_service.api_states
            logger.info(f"API states: {api_states}")
            if not api_states.get("gemini", False):
                raise ValueError("AI 서비스가 현재 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")
            
            logger.info("Gemini API state check passed")
            return True
            
        except Exception as e:
            logger.error(f"Error checking Gemini state: {e}", exc_info=True)
            if isinstance(e, ValueError):
                raise
            raise ValueError("AI 서비스 상태 확인에 실패했습니다") from e

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
            # Check Gemini state first
            await self._check_gemini_state()
            
            # Send typing indicator while processing
            async with ctx.typing():
                try:
                    # Get response from Gemini
                    response = await self.api_service.gemini.chat(message, ctx.author.id)
                    
                    # Split long responses into multiple messages
                    max_length = 4000  # Leave some buffer for embed formatting
                    if len(response) > max_length:
                        # Split response into chunks
                        chunks = [response[i:i+max_length] for i in range(0, len(response), max_length)]
                        
                        # Send first chunk as an embed
                        first_embed = discord.Embed(
                            description=chunks[0],
                            color=INFO_COLOR
                        )
                        await ctx.send(embed=first_embed)
                        
                        # Send remaining chunks as regular messages
                        for chunk in chunks[1:]:
                            await ctx.send(chunk)
                    else:
                        # Create embed for response
                        embed = discord.Embed(
                            description=response,
                            color=INFO_COLOR
                        )
                        
                        await ctx.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error in Gemini chat: {e}", exc_info=True)
                    raise ValueError("대화 처리 중 오류가 발생했습니다") from e
                
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
        description="AI와 대화를 시작합니다"
    )
    async def chat_slash(
        self,
        interaction: discord.Interaction,
        message: str,
        search: bool = False,
        private: bool = False
    ):
        """Start a chat with the AI."""
        try:
            # Check if Gemini API is available
            await self._check_gemini_state()
            
            # Create or get chat session
            chat = await self._get_or_create_chat_session(interaction, private)
            
            # Process the chat request
            response = await chat.send_message(
                message,
                enable_search=search
            )
            
            # Format and send response
            await self._process_response(interaction, response, private)
            
        except ValueError as e:
            # Handle known error states (API not available, etc)
            await interaction.response.send_message(
                str(e),
                ephemeral=True
            )
        except Exception as e:
            # Log unexpected errors
            logger.error(f"Error in chat command: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "AI 응답을 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                ephemeral=True
            )

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
            self._check_gemini_state()
            
            # Get user ID based on context type
            user_id = (
                ctx_or_interaction.author.id 
                if isinstance(ctx_or_interaction, commands.Context)
                else ctx_or_interaction.user.id
            )
            
            # Get response from Gemini
            response = await self.api_service.gemini.chat(message, user_id)
            
            # Split long responses into multiple messages
            max_length = 4000  # Leave some buffer for embed formatting
            if len(response) > max_length:
                # Split response into chunks
                chunks = [response[i:i+max_length] for i in range(0, len(response), max_length)]
                
                # Send first chunk as an embed
                first_embed = discord.Embed(
                    description=chunks[0],
                    color=INFO_COLOR
                )
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(embed=first_embed)
                else:
                    await ctx_or_interaction.send(embed=first_embed)
                
                # Send remaining chunks as regular messages
                for chunk in chunks[1:]:
                    if isinstance(ctx_or_interaction, discord.Interaction):
                        await ctx_or_interaction.followup.send(chunk)
                    else:
                        await ctx_or_interaction.send(chunk)
            else:
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
            # Create embed
            embed = discord.Embed(
                title="시스템 상태",
                color=INFO_COLOR
            )
            
            # Add API status section
            api_states = self.api_service.api_states
            status_text = []
            
            # API status icons
            status_icons = {
                True: "✅",
                False: "❌"
            }
            
            # Add API status information
            status_text.append("**API 상태:**")
            for api_name, is_active in api_states.items():
                icon = status_icons[is_active]
                status_text.append(f"{icon} {api_name.capitalize()}")
            
            # If Gemini is available, add detailed stats
            if api_states.get('gemini', False):
                try:
                    # Get formatted report
                    report = self.api_service.gemini.get_formatted_report()
                    embed.description = report
                    
                    # Get health status
                    health = self.api_service.gemini.health_status
                    
                    status_text.append("\n**서비스 상태:**")
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
                    status_text.append(f"\n**시스템 리소스:**")
                    status_text.append(f"🔄 CPU 사용량: {health['cpu_usage']:.1f}%")
                    status_text.append(f"💾 메모리 사용량: {health['memory_usage']:.1f}%")
                    
                    # Error count
                    if health["error_count"] > 0:
                        status_text.append(f"\n⚠️ 최근 오류: {health['error_count']}회")
                except Exception as e:
                    logger.error(f"Error getting Gemini stats: {e}")
                    status_text.append("\n⚠️ Gemini 상세 정보를 가져오는데 실패했습니다")
            else:
                status_text.append("\n**Gemini AI 서비스:**")
                status_text.append("❌ 현재 사용할 수 없음")
                status_text.append("AI 기능이 비활성화되어 있습니다")
            
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