import logging
from datetime import datetime
from typing import Dict, List, Optional, Type, cast, NoReturn, Union

import discord
from discord.app_commands import AppCommandError
from discord.ext import commands
from discord import app_commands

from src.services.memory_db import MemoryDB, MemoryInfo
from src.services.message_handler import MessageHandler
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR
from src.utils.version import get_git_info, VersionInfo
from src.commands.base_commands import BaseCommands
from src.commands.information import InformationCommands
from src.commands.entertainment import EntertainmentCommands
from src.commands.system import SystemCommands
from src.commands.arknights import ArknightsCommands
from src.services.api.service import APIService

logger = logging.getLogger(__name__)

HELP_DESCRIPTION = """
디스코드 봇 도움말

기본 명령어:
!안녕 - 봇과 인사하기
!주사위 [XdY] - 주사위 굴리기 (예: !주사위 2d6)
!투표 [선택지1] [선택지2] ... - 여러 선택지 중 하나를 무작위로 선택

정보 명령어:
!스팀 [게임이름] - 스팀 게임 정보와 현재 플레이어 수 확인
!날씨 - 현재 날씨 정보 확인
!시간 [지역] - 특정 지역의 현재 시간 확인
!인구 [국가] - 국가의 인구 정보 확인
!환율 - 현재 환율 정보 확인

시스템 명령어:
!핑 - 봇의 지연시간 확인
!복사 [메시지] - 봇이 메시지를 복사해서 보냄
"""


class DiscordBot(commands.Bot):
    """Main bot class handling commands and events"""

    def __init__(self, config: Dict[str, str], api_service: Optional[APIService] = None) -> None:
        """Initialize bot
        
        Args:
            config: Configuration dictionary containing API keys
            api_service: Optional APIService instance. If not provided, one will be created.
        """
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="!!",
            intents=intents,
            help_command=None  # Disable default help
        )

        self._config = config
        self._api_service = api_service
        self._command_classes: List[Type[BaseCommands]] = [
            InformationCommands,
            EntertainmentCommands,
            SystemCommands,
            ArknightsCommands
        ]
        self.memory_db: Optional[MemoryDB] = None
        self.version_info: VersionInfo = get_git_info()

    @property
    def api_service(self) -> APIService:
        """Get API service
        
        Returns:
            APIService: API service instance

        Raises:
            ValueError: If service not initialized
        """
        if not self._api_service:
            raise ValueError("API service not initialized")
        return self._api_service

    async def setup_hook(self) -> None:
        """Set up bot hooks and initialize services"""
        try:
            self.memory_db = MemoryDB()
            if not self._api_service:
                self._api_service = APIService(self._config)
                await self._api_service.initialize()
            await self._register_commands()
        except Exception as e:
            logger.error(f"Failed to setup bot: {e}")
            await self._cleanup()
            raise ValueError("봇 초기화에 실패했습니다") from e

    async def _register_commands(self) -> None:
        """Register all command classes"""
        try:
            for command_class in self._command_classes:
                if command_class == InformationCommands:
                    await self.add_cog(command_class(self.api_service))
                elif command_class == SystemCommands:
                    await self.add_cog(command_class(self))
                else:
                    await self.add_cog(command_class())
            await self.tree.sync()
            logger.info("Commands registered successfully")
        except Exception as e:
            logger.error(f"Failed to register commands: {e}")
            raise

    async def _cleanup(self) -> None:
        """Clean up resources"""
        if self._api_service:
            try:
                await self._api_service.close()
            except Exception as e:
                logger.error(f"Error during API service cleanup: {e}")
        self._api_service = None
        self.memory_db = None

    async def on_ready(self) -> None:
        """Handle bot ready event"""
        user = cast(discord.ClientUser, self.user)
        logger.info(
            f"Logged in as {user.name} "
            f"(Version: {self.version_info.version}, "
            f"Commit: {self.version_info.commit}, "
            f"Branch: {self.version_info.branch})"
        )
        await cast(discord.Client, self).change_presence(
            activity=discord.Game(
                name=f"!!help | /help | {self.version_info.commit}"
            )
        )

    async def on_command_error(
        self, 
        ctx: commands.Context, 
        error: commands.CommandError
    ) -> None:
        """Handle command errors
        
        Args:
            ctx: Command context
            error: Error that occurred
        """
        if isinstance(error, commands.CommandNotFound):
            return

        error_message = self._get_error_message(error)
        await self._send_error_message(cast(CommandContext, ctx), error_message)
        logger.error(f"Command error: {error}", exc_info=error)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ) -> None:
        """Handle slash command errors
        
        Args:
            interaction: Command interaction
            error: Error that occurred
        """
        error_message = self._get_error_message(error)
        await self._send_error_message(interaction, error_message)
        logger.error(f"Slash command error: {error}", exc_info=error)

    def _get_error_message(self, error: Exception) -> str:
        """Get user-friendly error message
        
        Args:
            error: Error to process

        Returns:
            str: Error message to display
        """
        if isinstance(error, commands.MissingPermissions):
            return "이 명령어를 실행할 권한이 없습니다"
        if isinstance(error, commands.BotMissingPermissions):
            return "봇에 필요한 권한이 없습니다"
        if isinstance(error, commands.MissingRequiredArgument):
            return f"필수 인자가 누락되었습니다: {error.param.name}"
        if isinstance(error, commands.BadArgument):
            return "잘못된 인자가 전달되었습니다"
        if isinstance(error, commands.CommandOnCooldown):
            return f"명령어 재사용 대기 시간입니다. {error.retry_after:.1f}초 후에 다시 시도해주세요"
        if isinstance(error, ValueError):
            return str(error)
        
        return "명령어 실행 중 오류가 발생했습니다"

    async def _send_error_message(
        self, 
        ctx_or_interaction: CommandContext, 
        error_message: str
    ) -> None:
        """Send error message to user
        
        Args:
            ctx_or_interaction: Command context or interaction
            error_message: Error message to send
        """
        embed = discord.Embed(
            title="❌ 오류",
            description=error_message,
            color=ERROR_COLOR
        )

        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await ctx_or_interaction.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

    async def close(self) -> None:
        """Clean up resources before closing"""
        try:
            await self._cleanup()
            await super().close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise

    @commands.command(name="환율")
    async def exchange_prefix(
        self,
        ctx: commands.Context,
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> None:
        """Show exchange rates"""
        await self._handle_exchange(ctx, currency, amount)

    @app_commands.command(name="exchange", description="환율 정보를 보여줍니다")
    async def exchange_slash(
        self,
        interaction: discord.Interaction,
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> None:
        """Show exchange rates"""
        await self._handle_exchange(interaction, currency, amount)

    async def _handle_exchange(
        self,
        ctx_or_interaction: CommandContext,
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> None:
        """Handle exchange rate command"""
        try:
            self._validate_amount(amount)
            rates = await self.api_service.exchange.get_exchange_rates()
            embed = await self._create_exchange_embed(rates, currency, amount)
            await self._send_response(ctx_or_interaction, embed=embed)
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in exchange command: {e}")
            raise ValueError("예상치 못한 오류가 발생했습니다") from e

    def _validate_amount(self, amount: float) -> None:
        """Validate exchange amount

        Args:
            amount: Amount to validate

        Raises:
            ValueError: If amount is invalid
        """
        if amount <= 0:
            raise ValueError("금액은 0보다 커야 합니다")
        if amount > 1000000000:
            raise ValueError("금액이 너무 큽니다 (최대: 1,000,000,000)")

    async def _get_exchange_rates(self) -> Dict[str, float]:
        """Get current exchange rates"""
        try:
            return await self.api_service.exchange.get_exchange_rates()
        except Exception as e:
            logger.error(f"Failed to get exchange rates: {e}")
            raise ValueError("환율 정보를 가져오는데 실패했습니다") from e

    async def _create_exchange_embed(
        self,
        rates: Dict[str, float],
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> discord.Embed:
        """Create exchange rate embed
        
        Args:
            rates: Exchange rates
            currency: Optional specific currency
            amount: Amount to convert

        Returns:
            discord.Embed: Formatted embed
        """
        embed = discord.Embed(
            title="💱 환율 정보",
            color=INFO_COLOR,
            timestamp=datetime.now()
        )

        if currency:
            if currency.upper() not in rates:
                raise ValueError(f"지원하지 않는 통화입니다: {currency}")
            rate = rates[currency.upper()]
            embed.add_field(
                name=f"KRW → {currency.upper()}",
                value=f"{amount:,.0f} KRW = {amount/rate:,.2f} {currency.upper()}",
                inline=False
            )
        else:
            for curr, rate in rates.items():
                embed.add_field(
                    name=f"KRW → {curr}",
                    value=f"{amount:,.0f} KRW = {amount/rate:,.2f} {curr}",
                    inline=True
                )

        return embed

    @discord.app_commands.command(name="remember", description="정보를 기억합니다")
    async def remember_slash(
        self,
        interaction: discord.Interaction,
        text: str,
        nickname: str
    ) -> None:
        """Remember information for a nickname"""
        await self._handle_remember(interaction, text, nickname)

    @commands.command(name="기억")
    async def remember_prefix(
        self,
        ctx: commands.Context,
        text: str,
        nickname: str
    ) -> None:
        """Remember information for a nickname"""
        await self._handle_remember(ctx, text, nickname)

    async def _handle_remember(
        self,
        ctx_or_interaction: CommandContext,
        text: str,
        nickname: str
    ) -> None:
        """Handle remember command
        
        Args:
            ctx_or_interaction: Command context or interaction
            text: Text to remember
            nickname: Nickname to associate with text
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)
            
            await self.memory_db.store(nickname, text)
            await self._send_remember_success_message(
                ctx_or_interaction,
                nickname,
                text,
                processing_msg
            )
        except Exception as e:
            logger.error(f"Error in remember command: {e}")
            await self._send_format_error_message(ctx_or_interaction, processing_msg)

    async def _show_processing_message(
        self,
        ctx_or_interaction: CommandContext
    ) -> Optional[discord.Message]:
        """Show processing message
        
        Args:
            ctx_or_interaction: Command context or interaction

        Returns:
            Optional[discord.Message]: Processing message if sent
        """
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer()
                return None
            else:
                return await ctx_or_interaction.send("처리 중...")
        except Exception as e:
            logger.error(f"Error showing processing message: {e}")
            return None

    async def _send_remember_success_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        text: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send success message for remember command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that was remembered
            text: Text that was stored
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 정보를 기억했습니다: {text}"
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @discord.app_commands.command(name="recall", description="정보를 알려줍니다")
    async def recall_slash(
        self,
        interaction: discord.Interaction,
        nickname: str
    ) -> None:
        """Recall information for a nickname"""
        await self._handle_recall(interaction, nickname)

    @commands.command(name="알려")
    async def recall_prefix(
        self,
        ctx: commands.Context,
        nickname: str
    ) -> None:
        """Recall information for a nickname"""
        await self._handle_recall(ctx, nickname)

    async def _handle_recall(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str
    ) -> None:
        """Handle recall command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname to recall information for
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)
            memories = await self.memory_db.recall(nickname)

            if memories:
                await self._send_memories_embed(
                    ctx_or_interaction,
                    nickname,
                    memories,
                    processing_msg
                )
            else:
                await self._send_no_memories_message(
                    ctx_or_interaction,
                    nickname,
                    processing_msg
                )

        except Exception as e:
            logger.error(f"Error in recall command: {e}")
            await self._send_error_message(ctx_or_interaction, str(e))

    async def _send_memories_embed(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        memories: Dict[str, MemoryInfo],
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send embed with memories
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname of memories
            memories: Memory information
            processing_msg: Optional processing message to delete
        """
        embed = discord.Embed(
            title=f"{nickname}의 정보",
            color=INFO_COLOR
        )

        for memory in memories.values():
            embed.add_field(
                name=memory["text"],
                value=f"입력: {memory['author']}\n시간: {memory['timestamp']}",
                inline=False
            )

        await self._send_response(ctx_or_interaction, embed=embed)
        if processing_msg:
            await processing_msg.delete()

    async def _send_no_memories_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send message when no memories found
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that had no memories
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 기억이 없습니다."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @discord.app_commands.command(name="forget", description="정보를 잊어버립니다")
    async def forget_slash(
        self,
        interaction: discord.Interaction,
        nickname: str
    ) -> None:
        """Forget information for a nickname"""
        await self._handle_forget(interaction, nickname)

    @commands.command(name="잊어")
    async def forget_prefix(
        self,
        ctx: commands.Context,
        nickname: str
    ) -> None:
        """Forget information for a nickname"""
        await self._handle_forget(ctx, nickname)

    async def _handle_forget(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str
    ) -> None:
        """Handle forget command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname to forget information for
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)

            if await self.memory_db.forget(nickname):
                await self._send_forget_success_message(
                    ctx_or_interaction,
                    nickname,
                    processing_msg
                )
            else:
                await self._send_forget_not_found_message(
                    ctx_or_interaction,
                    nickname,
                    processing_msg
                )

        except Exception as e:
            logger.error(f"Error in forget command: {e}")
            await self._send_format_error_message(ctx_or_interaction, processing_msg)

    async def _send_forget_success_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send success message for forget command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that was forgotten
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 모든 정보를 삭제했습니다."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    async def _send_forget_not_found_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send not found message for forget command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that wasn't found
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 정보를 찾을 수 없습니다."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @app_commands.command(name="help", description="도움말을 보여줍니다")
    async def help_slash(self, interaction: discord.Interaction) -> None:
        """Show help information"""
        await self._handle_help(interaction)

    @commands.command(name="도움말", aliases=["help"])
    async def help_prefix(self, ctx: commands.Context) -> None:
        """Show help information"""
        await self._handle_help(ctx)

    async def _handle_help(self, ctx_or_interaction: CommandContext) -> None:
        """Handle help command"""
        embed = discord.Embed(
            title="도움말",
            description=HELP_DESCRIPTION,
            color=INFO_COLOR
        )
        await self._send_response(ctx_or_interaction, embed=embed)

    @app_commands.command(name="memory", description="메모리 관리")
    async def memory_slash(
        self, 
        interaction: discord.Interaction,
        command_name: str,
        *,
        text: Optional[str] = None
    ) -> None:
        """Memory management command"""
        await self._handle_memory(interaction, command_name, text)

    @commands.command(name="기억", aliases=["memory"])
    async def memory_prefix(
        self,
        ctx: commands.Context,
        command_name: str,
        *,
        text: Optional[str] = None
    ) -> None:
        """Memory management command"""
        await self._handle_memory(ctx, command_name, text)

    async def _handle_memory(
        self,
        ctx_or_interaction: CommandContext,
        command_name: str,
        text: Optional[str] = None
    ) -> None:
        """Handle memory command"""
        try:
            if command_name == "저장":
                await self._store_memory(ctx_or_interaction, text)
            elif command_name == "목록":
                await self._list_memories(ctx_or_interaction)
            else:
                raise ValueError("알 수 없는 명령어입니다")
        except Exception as e:
            logger.error(f"Memory command error: {e}")
            raise ValueError("메모리 명령어 처리 중 오류가 발생했습니다") from e

    async def _store_memory(
        self,
        ctx_or_interaction: CommandContext,
        text: Optional[str]
    ) -> None:
        """Store memory for user"""
        if not self.memory_db:
            await self._initialize_memory_db()
        if not text:
            raise ValueError("저장할 내용을 입력해주세요")

        user_name = self.get_user_name(ctx_or_interaction)
        await self.memory_db.store(user_name, text)
        await self._send_response(
            ctx_or_interaction,
            f"'{text}' 를 기억했습니다!"
        )

    async def _initialize_memory_db(self) -> None:
        """Initialize memory database if not already initialized"""
        if not self.memory_db:
            self.memory_db = MemoryDB()

    async def _list_memories(self, ctx_or_interaction: CommandContext) -> None:
        """List memories for user"""
        if not self.memory_db:
            raise ValueError("Memory DB not initialized")

        user_name = self.get_user_name(ctx_or_interaction)
        memories = await self.memory_db.recall(user_name)
        
        if not memories:
            await self._send_response(
                ctx_or_interaction,
                "저장된 기억이 없습니다"
            )
            return

        embed = discord.Embed(
            title=f"{user_name}님의 기억",
            color=INFO_COLOR
        )
        for memory_id, memory in memories.items():
            embed.add_field(
                name=memory["timestamp"],
                value=memory["text"],
                inline=False
            )
        await self._send_response(ctx_or_interaction, embed=embed)

    @commands.command(name="동기화", help="슬래시 명령어를 동기화합니다")
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context) -> None:
        """Synchronize slash commands (admin only)
        
        Args:
            ctx: Command context
        """
        try:
            await self.tree.sync()
            await ctx.send("슬래시 명령어 동기화 완료!")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            raise ValueError("명령어 동기화에 실패했습니다") from e

    def get_user_name(self, ctx_or_interaction: CommandContext) -> str:
        """Get username from context or interaction"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.user.name
        return ctx_or_interaction.author.name

    def get_user_id(self, ctx_or_interaction: CommandContext) -> int:
        """Get user ID from context or interaction"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.user.id
        return ctx_or_interaction.author.id

    async def _send_response(
        self,
        ctx_or_interaction: CommandContext,
        content: Optional[str] = None,
        *,
        embed: Optional[discord.Embed] = None,
        ephemeral: bool = False
    ) -> None:
        """Send response to user"""
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(
                        content=content or "",
                        embed=embed or discord.Embed(),
                        ephemeral=ephemeral
                    )
                else:
                    await ctx_or_interaction.response.send_message(
                        content=content or "",
                        embed=embed or discord.Embed(),
                        ephemeral=ephemeral
                    )
            else:
                await ctx_or_interaction.send(
                    content=content or "",
                    embed=embed or discord.Embed()
                )
        except Exception as e:
            logger.error(f"Failed to send response: {e}")
            raise

    async def _send_format_error_message(
        self,
        ctx_or_interaction: CommandContext,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send format error message
        
        Args:
            ctx_or_interaction: Command context or interaction
            processing_msg: Optional processing message to delete
        """
        message = "올바른 형식이 아닙니다. '!!help'를 참고해주세요."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()
