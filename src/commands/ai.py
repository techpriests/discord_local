import logging
from typing import Optional, Dict, Any, Tuple
import uuid
from datetime import datetime
from collections import OrderedDict
import asyncio

import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button

from src.utils.decorators import command_handler
from .base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR
from src.services.api.service import APIService

logger = logging.getLogger(__name__)

# Constants
MAX_SOURCE_ENTRIES = 30000  # Maximum number of source entries to store

# Store source links temporarily using OrderedDict to maintain insertion order
class TimedSourceStorage(OrderedDict):
    """Extended OrderedDict that tracks timestamps and enforces a maximum size"""
    
    def __setitem__(self, key, value):
        """Set an item with timestamp and enforce size limit"""
        # If we're at capacity, remove oldest entry
        if len(self) >= MAX_SOURCE_ENTRIES:
            oldest_key = next(iter(self))
            logger.info(f"Source storage at capacity ({MAX_SOURCE_ENTRIES}). Removing oldest entry.")
            self.pop(oldest_key)
        
        # Store value with timestamp
        super().__setitem__(key, (value, datetime.now()))
    
    def __getitem__(self, key):
        """Get the value (without timestamp)"""
        value, _ = super().__getitem__(key)
        return value
    
    def get_entry_count(self):
        """Get current number of entries"""
        return len(self)

# Initialize storage for both sources and thinking content
source_storage = TimedSourceStorage()
thinking_storage = TimedSourceStorage()

class SourceView(View):
    """View with button to show sources (deprecated - kept for compatibility)"""
    
    def __init__(self, source_id: str):
        super().__init__()
        self.add_item(Button(
            label="참고 자료", 
            custom_id=f"sources_{source_id}",
            style=discord.ButtonStyle.secondary,
            disabled=True,  # Disabled since sources are now inline
            emoji="📚"
        ))

class ResponseView(View):
    """View with buttons for thinking content and sources"""
    
    def __init__(self, thinking_id: str = None, source_id: str = None):
        super().__init__()
        
        # Both buttons are temporarily hidden
        # To re-enable, uncomment the respective blocks below
        
        # Add thinking button if thinking content is available
        # if thinking_id:
        #     self.add_item(Button(
        #         label="추론 과정",
        #         custom_id=f"thinking_{thinking_id}",
        #         style=discord.ButtonStyle.primary,
        #         emoji="💭"
        #     ))
        
        # Add sources button (disabled since sources are inline)
        # if source_id:
        #     self.add_item(Button(
        #         label="참고 자료",
        #         custom_id=f"sources_{source_id}",
        #         style=discord.ButtonStyle.secondary,
        #         disabled=True,  # Disabled since sources are now inline
        #         emoji="📚"
        #     ))


class AICommands(BaseCommands):
    """AI-related commands including Claude integration"""

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
            raise ValueError("API 서비스가 초기화되지 않았어. 나중에 다시 시도해 줄래?")
        return self.bot.api_service

    async def _check_claude_state(self) -> bool:
        """Check if Claude API is available and ready for use.
        
        Returns:
            bool: True if Claude API is available
            
        Raises:
            ValueError: If Claude API is not available or not initialized
        """
        try:
            logger.info("Checking Claude API state...")
            
            # Check API service initialization
            logger.info(f"API service initialized: {self.api_service.initialized}")
            if not self.api_service.initialized:
                raise ValueError("API 서비스가 초기화되지 않았어. 잠시 후에 다시 해볼래?")
            
            # Check Claude API instance
            logger.info(f"Claude API instance present: {self.api_service.claude_api is not None}")
            if not self.api_service.claude_api:
                raise ValueError("AI 기능이 비활성화되어 있어. 관리자에게 문의해줘!")
            
            # Check Claude API state
            api_states = self.api_service.api_states
            logger.info(f"API states: {api_states}")
            if not api_states.get("claude", False):
                raise ValueError("AI 서비스가 현재 사용할 수 없는 상태야. 나중에 다시 올래?")
            
            logger.info("Claude API state check passed")
            return True
            
        except Exception as e:
            logger.error(f"Error checking Claude state: {e}", exc_info=True)
            if isinstance(e, ValueError):
                raise
            raise ValueError("AI 서비스 상태 확인에 실패했습니다") from e

    # Add method to handle button interactions
    async def handle_button_interaction(self, interaction: discord.Interaction) -> None:
        """Handle button interactions for source and thinking viewing
        
        Args:
            interaction: The button interaction
        """
        custom_id = interaction.data["custom_id"]
        
        if custom_id.startswith("thinking_"):
            thinking_id = custom_id.replace("thinking_", "")
            try:
                if thinking_id in thinking_storage:
                    thinking_content = thinking_storage[thinking_id]
                    
                    # Create embed with thinking content
                    embed = discord.Embed(
                        title="💭 추론 과정",
                        description=thinking_content,
                        color=INFO_COLOR
                    )
                    
                    # Send as a public message
                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message(
                        "추론 과정을 찾을 수 없어. 다시 물어봐줄래?",
                        ephemeral=True
                    )
            except Exception as e:
                logger.error(f"Error retrieving thinking content: {e}", exc_info=True)
                await interaction.response.send_message(
                    "추론 과정을 가져오는 중 오류가 발생했어. 잠시 후에 다시 시도해줘!",
                    ephemeral=True
                )
        elif custom_id.startswith("sources_"):
            source_id = custom_id.replace("sources_", "")
            try:
                if source_id in source_storage:
                    source_content = source_storage[source_id]
                    
                    # Create embed with sources
                    embed = discord.Embed(
                        title="📚 참고 자료",
                        description=source_content,
                        color=INFO_COLOR
                    )
                    
                    # Send as a public message
                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message(
                        "링크를 잊어버렸어 미안~ 다시 물어봐줄래?",
                        ephemeral=True
                    )
            except Exception as e:
                logger.error(f"Error retrieving sources: {e}", exc_info=True)
                await interaction.response.send_message(
                    "링크를 가져오는 중 오류가 발생했어. 잠시 후에 다시 시도해줘!",
                    ephemeral=True
                )

    @commands.command(
        name="기억소실",
        help="Clear sources history from memory",
        brief="Clear sources history",
        description="관리자 전용 명령어: 기억소실\n"
        "모든 소스 링크 히스토리를 삭제합니다."
    )
    @commands.is_owner()  # Only bot owner can use this command
    async def clear_sources(self, ctx: commands.Context) -> None:
        """Clear all stored sources from memory
        
        Args:
            ctx: Command context
        """
        try:
            # Get current number of stored sources and thinking content
            source_count = source_storage.get_entry_count()
            thinking_count = thinking_storage.get_entry_count()
            
            # Clear both storages
            source_storage.clear()
            thinking_storage.clear()
            
            # Send confirmation
            embed = discord.Embed(
                title="🧹 메모리 초기화",
                description=f"소스 기억 {source_count}개와 추론 과정 {thinking_count}개가 깨끗하게 지워졌어!",
                color=INFO_COLOR
            )
            await ctx.send(embed=embed)
            
            logger.info(f"Memory cleared: {source_count} sources, {thinking_count} thinking entries removed")
            
        except Exception as e:
            logger.error(f"Error clearing memory: {e}", exc_info=True)
            await ctx.send("메모리 초기화 중 오류가 발생했어. 다시 시도해볼래?")

    async def send_response(self, ctx_or_interaction: CommandContext, **kwargs) -> None:
        """Send response using the correct method based on context type
        
        Args:
            ctx_or_interaction: Command context or interaction
            **kwargs: Arguments to pass to send method
        """
        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                await ctx_or_interaction.followup.send(**kwargs)
            else:
                await ctx_or_interaction.response.send_message(**kwargs)
        else:
            await ctx_or_interaction.send(**kwargs)

    @commands.command(
        name="대화",
        help="뮤엘시스와 대화를 나눕니다",
        brief="뮤엘시스와 대화하기",
        aliases=["chat", "채팅", "알려줘"],
        description="뮤엘시스와 대화를 나누는 명령어입니다.\n"
        "대화는 30분간 지속되며, 이전 대화 내용을 기억합니다.\n\n"
        "사용법:\n"
        "• 뮤 알려줘 [메시지] - 뮤엘시스와 대화를 시작합니다\n"
        "• 뮤 대화종료 - 현재 진행 중인 대화를 종료합니다\n"
        "• 뮤 사용량 - 시스템 상태를 확인합니다\n\n"
        "제한사항:\n"
        "• 분당 최대 4회 요청 가능\n"
        "• 요청 간 5초 대기 시간\n"
        "• 대화는 30분 후 자동 종료\n\n"
        "예시:\n"
        "• 뮤 대화 안녕하세요\n"
        "• 뮤 알려줘 로도스 아일랜드에 대해 설명해줘\n"
        "• 뮤 알려줘줘 오리지늄이 뭐야?"
    )
    async def chat(self, ctx: commands.Context, *, message: str) -> None:
        """Chat with Claude AI
        
        Args:
            ctx: Command context
            message: Message to send to Claude
        """
        try:
            # Check Claude state first
            await self._check_claude_state()
            
            # Send typing indicator while processing
            async with ctx.typing():
                try:
                    # Get response from Claude
                    response, source_content, thinking_content = await self.api_service.claude.chat(message, ctx.author.id)
                    
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
                        
                        # Create view with thinking and source buttons
                        view = None
                        thinking_id = None
                        source_id = None
                        
                        if thinking_content:
                            thinking_id = str(uuid.uuid4())
                            thinking_storage[thinking_id] = thinking_content
                        
                        if source_content:
                            source_id = str(uuid.uuid4())
                            source_storage[source_id] = source_content
                        
                        if thinking_id or source_id:
                            view = ResponseView(thinking_id, source_id)
                        
                        await ctx.send(embed=first_embed, view=view)
                        
                        # Send remaining chunks as regular messages
                        for chunk in chunks[1:]:
                            await ctx.send(chunk)
                    else:
                        # Create embed for response
                        embed = discord.Embed(
                            description=response,
                            color=INFO_COLOR
                        )
                        
                        # Create view with thinking and source buttons
                        view = None
                        thinking_id = None
                        source_id = None
                        
                        if thinking_content:
                            thinking_id = str(uuid.uuid4())
                            thinking_storage[thinking_id] = thinking_content
                        
                        if source_content:
                            source_id = str(uuid.uuid4())
                            source_storage[source_id] = source_content
                        
                        if thinking_id or source_id:
                            view = ResponseView(thinking_id, source_id)
                        
                        await ctx.send(embed=embed, view=view)
                except Exception as e:
                    logger.error(f"Error in Claude chat: {e}", exc_info=True)
                    raise ValueError("대화 처리 중 오류가 발생했어. 더 간단한 질문으로 다시 시도해볼래?") from e
                
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
            raise ValueError("대화 처리에 실패했어. 미안! 잠시 후에 다시 해볼래?") from e

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
        import time
        start_time = time.time()
        
        try:
            # Immediately defer the response to prevent timeout
            defer_start = time.time()
            await interaction.response.defer(ephemeral=private)
            defer_time = time.time() - defer_start
            logger.info(f"Discord defer took: {defer_time:.3f}s")
            
            # Check Claude state
            await self._check_claude_state()
            
            # Get user ID
            user_id = interaction.user.id
            
            # Process through Claude API directly
            api_start = time.time()
            response, source_content, thinking_content = await self.api_service.claude.chat(message, user_id)
            api_time = time.time() - api_start
            logger.info(f"Claude API took: {api_time:.3f}s")
            
            # Format response for Discord
            format_start = time.time()
            max_length = 4000  # Leave buffer for embed formatting
            embed_data = None
            view = None
            
            # Continue formatting response
            
            if len(response) > max_length:
                # Split response into chunks
                chunks = [response[i:i+max_length] for i in range(0, len(response), max_length)]
                
                # Send first chunk as an embed
                first_embed = discord.Embed(
                    description=chunks[0],
                    color=INFO_COLOR
                )
                
                # Create view with thinking and source buttons
                view = None
                thinking_id = None
                source_id = None
                
                if thinking_content:
                    thinking_id = str(uuid.uuid4())
                    thinking_storage[thinking_id] = thinking_content
                
                if source_content:
                    source_id = str(uuid.uuid4())
                    source_storage[source_id] = source_content
                
                if thinking_id or source_id:
                    view = ResponseView(thinking_id, source_id)
                
                # Send first response
                await interaction.followup.send(embed=first_embed, view=view)
                
                # Send remaining chunks
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                # Create embed for response
                embed = discord.Embed(
                    description=response,
                    color=INFO_COLOR
                )
                
                # Create view with thinking and source buttons
                view = None
                thinking_id = None
                source_id = None
                
                if thinking_content:
                    thinking_id = str(uuid.uuid4())
                    thinking_storage[thinking_id] = thinking_content
                
                if source_content:
                    source_id = str(uuid.uuid4())
                    source_storage[source_id] = source_content
                
                if thinking_id or source_id:
                    view = ResponseView(thinking_id, source_id)
                
                # Send response with timeout protection
                followup_start = time.time()
                try:
                    # Try followup first with a reasonable timeout
                    await asyncio.wait_for(
                        interaction.followup.send(embed=embed, view=view),
                        timeout=15.0  # 15 second timeout for Discord followup
                    )
                    followup_time = time.time() - followup_start
                    total_time = time.time() - start_time
                    logger.info(f"Discord followup took: {followup_time:.3f}s")
                    logger.info(f"Total command time: {total_time:.3f}s")
                except asyncio.TimeoutError:
                    logger.warning("Discord followup timed out, falling back to channel message")
                    # Fallback: send directly to channel
                    await interaction.channel.send(
                        f"{interaction.user.mention}",
                        embed=embed,
                        view=view
                    )
                    fallback_time = time.time() - followup_start
                    total_time = time.time() - start_time
                    logger.info(f"Discord fallback took: {fallback_time:.3f}s")
                    logger.info(f"Total command time: {total_time:.3f}s")
                
                format_time = time.time() - format_start
                logger.info(f"Discord formatting took: {format_time:.3f}s")
                
        except ValueError as e:
            # Handle expected errors
            if interaction.response.is_done():
                await interaction.followup.send(str(e), ephemeral=True)
            else:
                await interaction.response.send_message(str(e), ephemeral=True)
        except Exception as e:
            # Log unexpected errors
            logger.error(f"Error in chat slash command: {str(e)}", exc_info=True)
            
            error_msg = "응답을 처리하는 중 문제가 생겼어. 잠시 후에 다시 해볼래?"
            
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    @command_handler()
    async def _handle_chat(
        self,
        ctx_or_interaction: CommandContext,
        message: str
    ) -> None:
        """Handle chat command
        
        Args:
            ctx_or_interaction: Command context or interaction
            message: Message to send to Claude
        """
        try:
            await self._check_claude_state()
            
            # Get user ID based on context type
            user_id = (
                ctx_or_interaction.author.id 
                if isinstance(ctx_or_interaction, commands.Context)
                else ctx_or_interaction.user.id
            )
            
            # Get response from Claude
            response, source_content, thinking_content = await self.api_service.claude.chat(message, user_id)
            
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
                
                # Create view with thinking and source buttons
                view = None
                thinking_id = None
                source_id = None
                
                if thinking_content:
                    thinking_id = str(uuid.uuid4())
                    thinking_storage[thinking_id] = thinking_content
                
                if source_content:
                    source_id = str(uuid.uuid4())
                    source_storage[source_id] = source_content
                
                if thinking_id or source_id:
                    view = ResponseView(thinking_id, source_id)
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(embed=first_embed, view=view)
                else:
                    await ctx_or_interaction.send(embed=first_embed, view=view)
                
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
                
                # Create view with thinking and source buttons
                view = None
                thinking_id = None
                source_id = None
                
                if thinking_content:
                    thinking_id = str(uuid.uuid4())
                    thinking_storage[thinking_id] = thinking_content
                
                if source_content:
                    source_id = str(uuid.uuid4())
                    source_storage[source_id] = source_content
                
                if thinking_id or source_id:
                    view = ResponseView(thinking_id, source_id)
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(embed=embed, view=view)
                else:
                    await ctx_or_interaction.send(embed=embed, view=view)
                
        except ValueError as e:
            # Handle API errors
            error_embed = discord.Embed(
                title="⚠️ AI 채팅 오류",
                description=f"앗, 에러야! {str(e)}",
                color=discord.Color.red(),
            )
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=error_embed)
            else:
                await ctx_or_interaction.send(embed=error_embed)
        except Exception as e:
            logger.error(f"Error in chat command: {e}", exc_info=True)
            raise ValueError("대화 처리에 실패했어. 다시 한번 시도해 볼래?") from e

    @commands.command(
        name="사용량",
        help="시스템 상태와 사용량을 확인합니다",
        brief="시스템 상태 확인",
        aliases=["usage", "상태"],
        description="현재 시스템 상태와 사용량을 보여줘.\n"
        "토큰 사용량, CPU/메모리 사용량, 오류 상태 등을 확인할 수 있어.\n\n"
        "사용법:\n"
        "• 뮤 사용량 - 전체 시스템 상태 확인\n"
        "• pt usage\n\n"
        "표시 정보:\n"
        "• 현재 분당 요청 수\n"
        "• 일간 토큰 사용량\n"
        "• CPU/메모리 사용량\n"
        "• 시스템 상태 및 오류"
    )
    async def usage_prefix(self, ctx: commands.Context) -> None:
        """Show Claude AI usage statistics"""
        await self._handle_usage(ctx)

    @app_commands.command(
        name="ai_usage",
        description="Claude AI 사용량을 보여줘"
    )
    async def usage_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for showing Claude AI usage statistics"""
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
            
            # If Claude is available, add detailed stats
            if api_states.get('claude', False):
                try:
                    # Get formatted report
                    report = self.api_service.claude.get_formatted_report()
                    embed.description = report
                    
                    # Get health status
                    health = self.api_service.claude.health_status
                    
                    status_text.append("\n**서비스 상태:**")
                    # Service status
                    if not health["is_enabled"]:
                        status_text.append("❌ 서비스가가 비활성화되어 있어")
                        if health["time_until_enable"]:
                            minutes = int(health["time_until_enable"] / 60)
                            status_text.append(f"⏳ {minutes}분 후에 다시 이용할 수 있을 거야!")
                    elif health["is_slowed_down"]:
                        status_text.append("⚠️ 지금은 좀 느릴 수 있어")
                        if health["time_until_slowdown_reset"]:
                            minutes = int(health["time_until_slowdown_reset"] / 60)
                            status_text.append(f"⏳ {minutes}분 후에 다시 정상 속도로 돌아갈 거야!")
                    else:
                        status_text.append("✅ 모든 게 정상이야! 대화해 볼래?")
                    
                    # System metrics
                    status_text.append(f"\n**시스템 리소스:**")
                    status_text.append(f"🔄 CPU 사용량: {health['cpu_usage']:.1f}%")
                    status_text.append(f"💾 메모리 사용량: {health['memory_usage']:.1f}%")
                    
                    # Error count
                    if health["error_count"] > 0:
                        status_text.append(f"\n⚠️ 최근 오류: {health['error_count']}회")
                except Exception as e:
                    logger.error(f"Error getting Claude stats: {e}")
                    status_text.append("\n⚠️ Claude 상세 정보를 가져오는데 실패했어. 미안해!")
            else:
                status_text.append("\n**Claude AI 서비스:**")
                status_text.append("❌ 현재 사용할 수 없어. 미안해!")
                status_text.append("AI 기능이 일시적으로 꺼져있어. 나중에 다시 와볼래?")
            
            embed.add_field(
                name="시스템 상태",
                value="\n".join(status_text),
                inline=False
            )
            
            await self.send_response(ctx_or_interaction, embed=embed)
            
        except Exception as e:
            logger.error(f"Error getting usage statistics: {e}")
            raise ValueError("사용량 정보를 가져오는데 실패했어. 미안!") from e

    @commands.command(
        name="생각모드",
        help="Extended thinking 모드를 설정합니다",
        brief="생각 모드 설정",
        aliases=["thinking", "생각"],
        description="뮤엘시스의 생각 모드를 설정해.\n"
        "복잡한 질문에 대해 더 깊이 생각할 수 있게 해줘.\n\n"
        "사용법:\n"
        "• 뮤 생각모드 - 현재 설정 확인\n"
        "• 뮤 생각모드 켜기 - 생각 모드 활성화\n"
        "• 뮤 생각모드 끄기 - 생각 모드 비활성화 (기본값)\n\n"
        "참고:\n"
        "• 생각 모드는 복잡한 추론이 필요한 질문에 유용해\n"
        "• 토큰 사용량이 증가할 수 있어 (1024 토큰 예산)\n"
        "• Claude가 필요하다고 판단할 때만 실제로 생각해",
        hidden=True  # Hide from help command for regular users
    )
    @commands.is_owner()  # Only bot owner can configure thinking
    async def thinking_mode(self, ctx: commands.Context, mode: str = None) -> None:
        """Configure thinking mode"""
        try:
            claude_api = self.api_service.claude
            
            if mode is None:
                # Show current configuration
                config = claude_api.get_thinking_config()
                status = "켜짐" if config["enabled"] else "꺼짐"
                
                embed = discord.Embed(
                    title="🧠 생각 모드 설정",
                    color=INFO_COLOR
                )
                embed.add_field(
                    name="현재 상태",
                    value=status,
                    inline=False
                )
                embed.add_field(
                    name="토큰 예산",
                    value=f"{config['budget_tokens']:,} 토큰",
                    inline=True
                )
                embed.add_field(
                    name="사용된 생각 토큰",
                    value=f"{config['tokens_used']:,} 토큰",
                    inline=True
                )
                embed.add_field(
                    name="모드 설명",
                    value="• **켜기**: 모든 질문에 생각 모드 활성화 (토큰 사용량 증가)\n"
                          "• **끄기**: 생각 모드 비활성화 (기본값, 효율적)",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                return
            
            mode_lower = mode.lower()
            
            if mode_lower in ["켜기", "on", "enable", "켜", "활성화"]:
                claude_api.configure_thinking(enabled=True, budget_tokens=1024)
                await ctx.send("🧠 생각 모드가 **활성화**되었어! 토큰 사용량이 증가할 수 있어.")
                
            elif mode_lower in ["끄기", "off", "disable", "꺼", "비활성화"]:
                claude_api.configure_thinking(enabled=False, budget_tokens=1024)
                await ctx.send("🧠 생각 모드가 **비활성화**되었어. 토큰 사용량이 줄어들 거야.")
                
            else:
                await ctx.send("❌ 올바른 모드를 입력해줘: `켜기`, `끄기`")
                
        except Exception as e:
            logger.error(f"Error in thinking mode command: {e}", exc_info=True)
            await ctx.send("❌ 생각 모드 설정 중 오류가 발생했어.")

    @commands.command(
        name="대화기록",
        help="현재 대화 세션의 기록을 확인합니다",
        brief="대화 기록 확인",
        aliases=["history", "기록"],
        description="현재 진행 중인 대화 세션의 메시지 기록을 보여줘.\n"
        "디버깅 및 문제 해결용 명령어야.\n\n"
        "사용법:\n"
        "• 뮤 대화기록 - 현재 대화 세션 기록 확인\n\n"
        "참고:\n"
        "• 관리자 전용 명령어\n"
        "• 세션이 없으면 '대화 기록 없음'이 표시돼",
        hidden=True  # Hide from help command for regular users
    )
    @commands.is_owner()  # Only bot owner can view conversation history
    async def conversation_history(self, ctx: commands.Context) -> None:
        """Show current conversation history for debugging"""
        try:
            claude_api = self.api_service.claude
            user_id = ctx.author.id
            
            # Get conversation session
            if user_id not in claude_api._chat_sessions:
                await ctx.send("📭 현재 진행 중인 대화 세션이 없어.")
                return
                
            messages = claude_api._chat_sessions[user_id]
            
            if not messages:
                await ctx.send("📭 대화 기록이 비어있어.")
                return
            
            # Create debug embed
            embed = discord.Embed(
                title="🔍 대화 기록 (디버그)",
                description=f"총 {len(messages)}개의 메시지",
                color=INFO_COLOR
            )
            
            # Show last few messages for debugging
            for i, msg in enumerate(messages[-6:], 1):  # Show last 6 messages
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                
                # Handle different content types
                if isinstance(content, list):
                    # Complex content with blocks
                    content_summary = []
                    for block in content:
                        if isinstance(block, dict):
                            block_type = block.get("type", "unknown")
                            if block_type == "text":
                                text = block.get("text", "")[:100]
                                content_summary.append(f"[텍스트] {text}...")
                            elif block_type == "thinking":
                                content_summary.append("[생각 블록]")
                            elif block_type == "redacted_thinking":
                                content_summary.append("[암호화된 생각]")
                            else:
                                content_summary.append(f"[{block_type}]")
                    content_display = "\n".join(content_summary)
                else:
                    # Simple text content
                    content_display = content[:200] + "..." if len(content) > 200 else content
                
                embed.add_field(
                    name=f"{i}. {role.title()}",
                    value=content_display or "(내용 없음)",
                    inline=False
                )
            
            if len(messages) > 6:
                embed.add_field(
                    name="참고",
                    value=f"더 많은 메시지가 있어 (총 {len(messages)}개, 최근 6개만 표시)",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in conversation history command: {e}", exc_info=True)
            await ctx.send("❌ 대화 기록을 확인하는 중 오류가 발생했어.")

    @commands.command(
        name="대화종료",
        help="현재 진행 중인 대화 세션을 종료할거야",
        brief="대화 세션 종료하기",
        aliases=["endchat", "세션종료"],
        description="현재 진행 중인 대화를 종료해.\n"
        "대화가 종료되면 이전 대화 내용은 더 이상 기억되지 않아.\n\n"
        "사용법:\n"
        "• 뮤 대화종료 - 현재 대화 세션을 즉시 종료\n"
        "• pt endchat\n\n"
        "참고:\n"
        "• 대화는 30분 동안 활동이 없으면 자동으로 종료돼\n"
        "• 새로운 대화는 뮤 대화 명령어로 언제든 시작할 수 있어"
    )
    async def end_chat(self, ctx: commands.Context) -> None:
        """End current chat session"""
        try:
            if self.api_service.claude.end_chat_session(ctx.author.id):
                embed = discord.Embed(
                    title="✅ 대화 세션 종료",
                    description="대화 세션이 끝났어!\n새로운 대화를 언제든 시작할 수 있어.",
                    color=INFO_COLOR
                )
            else:
                embed = discord.Embed(
                    title="ℹ️ 알림",
                    description="진행 중인 대화 세션이 없어. 새로운 대화를 시작해볼래?",
                    color=INFO_COLOR
                )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in end_chat command: {e}")
            raise ValueError("대화 세션 종료에 실패했어. 다시 시도해볼래?") from e 