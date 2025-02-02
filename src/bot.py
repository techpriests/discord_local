import logging
from datetime import datetime
from typing import Dict, List, Optional

import discord
from discord.app_commands import AppCommandError
from discord.ext import commands

from src.services.memory_db import MemoryDB
from src.services.message_handler import MessageHandler

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


class DiscordBot:
    """Main Discord bot class that handles core functionality."""

    def __init__(self):
        """Initialize the Discord bot with required intents and settings."""
        intents = discord.Intents.all()
        self.bot = commands.Bot(command_prefix="!!", intents=intents)
        self.api_service = None
        self.memory_db = MemoryDB()

        @self.bot.event
        async def on_ready():
            """Handle bot ready event."""
            print(f"{self.bot.user.name} 로그인 성공")
            await self.bot.change_presence(
                status=discord.Status.online, activity=discord.Game("LIVE")
            )

    async def load_cogs(self, cogs: List[commands.Cog], api_service=None):
        """Load cogs asynchronously"""
        self.api_service = api_service
        for cog in cogs:
            await self.bot.add_cog(cog)
        # Add message handler
        await self.bot.add_cog(MessageHandler(self.bot))

    async def start(self, token: str):
        """Start the bot"""
        try:
            await self.bot.start(token)
        except discord.LoginFailure as e:
            logger.error(f"Failed to login: {e}")
            raise ValueError("봇 토큰이 잘못되었습니다") from e
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise ValueError("봇 시작에 실패했습니다") from e
        finally:
            if self.api_service:
                await self.api_service.close()

    @discord.app_commands.command(name="exchange", description="환율 정보를 보여줍니다")
    async def exchange_slash(
        self, interaction: discord.Interaction, currency: str = None, amount: float = 1.0
    ):
        """Slash command version"""
        await self._handle_exchange(interaction, currency, amount)

    @commands.command(name="환율", aliases=["exchange"])
    async def exchange_prefix(
        self, ctx: commands.Context, currency: str = None, amount: float = 1.0
    ):
        """Prefix command version"""
        await self._handle_exchange(ctx, currency, amount)

    async def _handle_exchange(self, ctx_or_interaction, currency: str = None, amount: float = 1.0):
        """Handle exchange rate conversion command

        Args:
            ctx_or_interaction: Command context or interaction
            currency: Optional currency code to convert
            amount: Amount to convert (default: 1.0)

        Raises:
            ValueError: If amount is invalid or currency not supported
        """
        try:
            self._validate_amount(amount)
            rates = await self._get_exchange_rates()
            embed = await self._create_exchange_embed(rates, currency, amount)
            return await self._send_response(ctx_or_interaction, embed=embed)

        except ValueError as e:
            raise e  # Re-raise user input errors
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
        """Get current exchange rates

        Returns:
            Dict[str, float]: Exchange rates

        Raises:
            ValueError: If failed to get rates
        """
        try:
            return await self.api_service.exchange.get_exchange_rates()
        except Exception as e:
            logger.error(f"Failed to get exchange rates: {e}")
            raise ValueError("환율 정보를 가져오는데 실패했습니다") from e

    async def _create_exchange_embed(
        self, rates: Dict[str, float], currency: Optional[str] = None, amount: float = 1.0
    ) -> discord.Embed:
        """Create embed for exchange rate display

        Args:
            rates: Exchange rates
            currency: Optional specific currency to show
            amount: Amount to convert

        Returns:
            discord.Embed: Formatted embed with exchange rates

        Raises:
            ValueError: If currency is not supported
        """
        try:
            embed = discord.Embed(
                title="💱 환율 정보", color=discord.Color.blue(), timestamp=datetime.now()
            )

            if currency:
                currency_code = currency.upper()
                if currency_code not in rates:
                    supported_currencies = ", ".join(rates.keys())
                    raise ValueError(
                        f"지원하지 않는 통화입니다: {currency}\n"
                        f"지원되는 통화: {supported_currencies}"
                    )

                krw_amount = amount * rates[currency_code]
                embed.description = f"{amount:,.2f} {currency_code} = {krw_amount:,.2f} KRW"
            else:
                base_amount = 1000
                for curr, rate in rates.items():
                    foreign_amount = base_amount / rate
                    embed.add_field(
                        name=curr,
                        value=f"{base_amount:,.0f} KRW = {foreign_amount:,.2f} {curr}",
                        inline=True,
                    )

            embed.set_footer(text="Data from ExchangeRate-API")
            return embed

        except Exception as e:
            logger.error(f"Failed to create exchange rate response: {e}")
            raise ValueError("환율 정보 표시에 실패했습니다") from e

    @discord.app_commands.command(name="remember", description="정보를 기억합니다")
    async def remember_slash(self, interaction: discord.Interaction, text: str, nickname: str):
        """Slash command version"""
        await self._handle_remember(interaction, text, nickname)

    @commands.command(name="기억")
    async def remember_prefix(self, ctx: commands.Context, text: str, nickname: str):
        """Prefix command version"""
        await self._handle_remember(ctx, text, nickname)

    async def _handle_remember(self, ctx_or_interaction, text: str, nickname: str):
        """Handle remember command to store new memories

        Args:
            ctx_or_interaction: Command context or interaction
            text: Text to remember
            nickname: User nickname to associate with the memory
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)
            author = self._get_author(ctx_or_interaction)

            if self.memory_db.remember(text, nickname, author):
                await self._send_success_message(ctx_or_interaction, text, nickname, processing_msg)
            else:
                await self._send_failure_message(ctx_or_interaction, processing_msg)

        except Exception:
            await self._send_format_error_message(ctx_or_interaction, processing_msg)

    def _get_author(self, ctx_or_interaction):
        """Get author's string representation"""
        return str(
            ctx_or_interaction.user
            if isinstance(ctx_or_interaction, discord.Interaction)
            else ctx_or_interaction.author
        )

    async def _send_success_message(self, ctx_or_interaction, text, nickname, processing_msg=None):
        """Send success message for remember command"""
        message = f"기억했습니다: {text} → {nickname}"
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    async def _send_failure_message(self, ctx_or_interaction, processing_msg=None):
        """Send failure message for remember command"""
        message = "기억하는데 실패했습니다."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @discord.app_commands.command(name="recall", description="정보를 알려줍니다")
    async def recall_slash(self, interaction: discord.Interaction, nickname: str):
        """Slash command version"""
        await self._handle_recall(interaction, nickname)

    @commands.command(name="알려")
    async def recall_prefix(self, ctx: commands.Context, nickname: str):
        """Prefix command version"""
        await self._handle_recall(ctx, nickname)

    async def _handle_recall(self, ctx_or_interaction, nickname: str):
        """Handle recall command to show stored memories

        Args:
            ctx_or_interaction: Command context or interaction
            nickname: User nickname to recall memories for
        """
        try:
            await self._show_processing_message(ctx_or_interaction)
            memories = self.memory_db.recall(nickname)

            if memories:
                await self._send_memories_embed(ctx_or_interaction, nickname, memories)
            else:
                await self._send_no_memories_message(ctx_or_interaction, nickname)

        except Exception as e:
            logger.error(f"Error in recall command: {e}")
            await self._send_error_message(ctx_or_interaction)

    async def _show_processing_message(self, ctx_or_interaction):
        """Show processing message to user"""
        user_name = self._get_user_name(ctx_or_interaction)
        processing_text = f"{user_name}님의 명령어를 처리중입니다..."

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.defer(ephemeral=True)
            await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
        else:
            return await ctx_or_interaction.send(processing_text)

    def _get_user_name(self, ctx_or_interaction):
        """Get user's display name"""
        return (
            ctx_or_interaction.user.display_name
            if isinstance(ctx_or_interaction, discord.Interaction)
            else ctx_or_interaction.author.display_name
        )

    async def _send_memories_embed(self, ctx_or_interaction, nickname, memories):
        """Send embed with memories"""
        embed = discord.Embed(title=f"{nickname}의 정보", color=discord.Color.blue())

        for memory in memories.values():
            embed.add_field(
                name=memory["text"],
                value=f"입력: {memory['author']}\n시간: {memory['timestamp']}",
                inline=False,
            )

        await self._send_response(ctx_or_interaction, embed=embed)

    async def _send_no_memories_message(self, ctx_or_interaction, nickname):
        """Send message when no memories found"""
        message = f"'{nickname}'에 대한 기억이 없습니다."
        await self._send_response(ctx_or_interaction, message)

    async def _send_error_message(self, ctx_or_interaction):
        """Send error message"""
        message = "기억을 불러오는데 실패했습니다."
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.followup.send(message, ephemeral=True)
        else:
            await ctx_or_interaction.send(message)

    @discord.app_commands.command(name="forget", description="정보를 잊어버립니다")
    async def forget_slash(self, interaction: discord.Interaction, nickname: str):
        """Slash command version"""
        await self._handle_forget(interaction, nickname)

    @commands.command(name="잊어")
    async def forget_prefix(self, ctx: commands.Context, nickname: str):
        """Prefix command version"""
        await self._handle_forget(ctx, nickname)

    async def _handle_forget(self, ctx_or_interaction, nickname: str):
        """Handle forget command to remove memories

        Args:
            ctx_or_interaction: Command context or interaction
            nickname: User nickname to forget memories for
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)

            if self.memory_db.forget(nickname):
                await self._send_forget_success_message(
                    ctx_or_interaction, nickname, processing_msg
                )
            else:
                await self._send_forget_not_found_message(
                    ctx_or_interaction, nickname, processing_msg
                )

        except Exception as e:
            logger.error(f"Error in forget command: {e}")
            await self._send_format_error_message(ctx_or_interaction, processing_msg)

    async def _send_forget_success_message(self, ctx_or_interaction, nickname, processing_msg=None):
        """Send success message for forget command"""
        message = f"'{nickname}'에 대한 모든 정보를 삭제했습니다."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    async def _send_forget_not_found_message(
        self, ctx_or_interaction, nickname, processing_msg=None
    ):
        """Send not found message for forget command"""
        message = f"'{nickname}'에 대한 정보를 찾을 수 없습니다."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @commands.command(
        name="help",
        help="명령어 도움말을 보여줍니다",
        brief="도움말",
        description=HELP_DESCRIPTION,  # Move long description to constant
    )
    async def help(self, ctx, command_name: str = None):
        """Show help information for commands

        Args:
            ctx: Command context
            command_name: Optional specific command to show help for
        """
        if command_name:
            embed = await self._create_command_help_embed(command_name)
        else:
            embed = await self._create_general_help_embed()

        await ctx.send(embed=embed)

    async def _create_command_help_embed(self, command_name: str) -> discord.Embed:
        """Create help embed for specific command

        Args:
            command_name: Name of command to show help for

        Returns:
            discord.Embed: Formatted help embed
        """
        command = self.bot.get_command(command_name)
        if command:
            embed = discord.Embed(
                title=f"💡 {command.name} 명령어 도움말",
                description=command.description,
                color=discord.Color.blue(),
            )
            if command.aliases:
                embed.add_field(
                    name="다른 사용법",
                    value=", ".join(f"!!{alias}" for alias in command.aliases),
                    inline=False,
                )
        else:
            embed = discord.Embed(
                title="❌ 오류",
                description=f"'{command_name}' 명령어를 찾을 수 없습니다.",
                color=discord.Color.red(),
            )
        return embed

    async def _create_general_help_embed(self) -> discord.Embed:
        """Create general help embed

        Returns:
            discord.Embed: Formatted help embed
        """
        embed = discord.Embed(
            title="🤖 도움말", description=self.help.description, color=discord.Color.blue()
        )
        embed.set_footer(text="자세한 사용법은 !!help [명령어] 를 입력해주세요")
        return embed

    async def setup_hook(self):
        """Set up error handlers and other hooks."""
        self.tree.on_error = self.on_app_command_error

    async def on_app_command_error(self, interaction: discord.Interaction, error: AppCommandError):
        """Handle slash command errors

        Args:
            interaction: Slash command interaction
            error: The error that occurred
        """
        if isinstance(error, commands.CommandOnCooldown):
            await self._handle_cooldown_error(interaction, error)
        else:
            await self._handle_unexpected_slash_error(interaction, error)

    async def _handle_cooldown_error(
        self, interaction: discord.Interaction, error: commands.CommandOnCooldown
    ):
        """Handle command cooldown errors

        Args:
            interaction: Slash command interaction
            error: Cooldown error
        """
        await interaction.response.send_message(
            f"명령어 사용 제한 중입니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.",
            ephemeral=True,
        )

    async def _handle_unexpected_slash_error(
        self, interaction: discord.Interaction, error: Exception
    ):
        """Handle unexpected slash command errors

        Args:
            interaction: Slash command interaction
            error: The unexpected error
        """
        logger.error(f"Slash command error in {interaction.command}: {error}")
        error_messages = self._get_error_messages()
        await interaction.response.send_message("\n".join(error_messages), ephemeral=True)

    def _get_error_messages(self) -> List[str]:
        """Get list of error messages

        Returns:
            List[str]: Error messages to display
        """
        return [
            "예상치 못한 오류가 발생했습니다.",
            "가능한 해결 방법:",
            "• 잠시 후 다시 시도",
            "• 명령어 사용법 확인 (`/help` 명령어 사용)",
            "• 봇 관리자에게 문의",
        ]

    # Add separate command for syncing
    @commands.command(name="동기화", help="슬래시 명령어를 동기화합니다")
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx):
        """Synchronize slash commands (admin only)."""
        await self.bot.tree.sync()
        await ctx.send("슬래시 명령어 동기화 완료!")
