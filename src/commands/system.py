import logging
from typing import Union, Optional

import discord
from discord.ext import commands

from src.utils.decorators import command_handler
from .base_commands import BaseCommands

# Constants for embed colors
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
INFO_COLOR = discord.Color.blue()

logger = logging.getLogger(__name__)


class SystemCommands(BaseCommands):
    """System-related commands for bot management"""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize system commands

        Args:
            bot: Discord bot instance
        """
        super().__init__()
        self.bot = bot

    @commands.command(name="핑")
    async def ping(self, ctx: commands.Context) -> None:
        """Show bot latency"""
        try:
            latency = round(self.bot.latency * 1000)
            await ctx.send(f"🏓 퐁! ({latency}ms)")
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["send_messages"])
        except Exception as e:
            logger.error(f"Error in ping command: {e}")
            raise ValueError("지연시간을 측정할 수 없습니다")

    @commands.command(name="복사")
    async def echo(self, ctx: commands.Context, *, message: str) -> None:
        """Echo back a message
        
        Args:
            ctx: Command context
            message: Message to echo
        """
        try:
            await ctx.message.delete()
            await ctx.send(message)
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["manage_messages"])
        except Exception as e:
            logger.error(f"Error in echo command: {e}")
            raise ValueError("메시지를 복사할 수 없습니다")

    @commands.command(
        name="따라해",
        help="메시지를 따라합니다",
        brief="메시지 따라하기",
        aliases=["copy", "mimic"],
        description=(
            "입력한 메시지를 그대로 따라합니다.\n"
            "사용법: !!따라해 [메시지]\n"
            "예시: !!따라해 안녕하세요"
        ),
    )
    async def copy_message(self, ctx: commands.Context, *, message: str) -> None:
        """Copy and resend the given message

        Args:
            ctx: Command context
            message: Message to copy

        Raises:
            discord.Forbidden: If bot lacks permission to delete messages
        """
        try:
            await ctx.message.delete()
            await ctx.send(message)
        except discord.Forbidden as e:
            logger.error(f"Permission error in copy_message: {e}")
            raise discord.Forbidden("메시지를 삭제할 권한이 없습니다.") from e
        except Exception as e:
            logger.error(f"Error in copy_message: {e}")
            raise ValueError("메시지 복사에 실패했습니다") from e

    @commands.command(aliases=["quit"])
    @commands.has_permissions(administrator=True)
    async def close(self, ctx: commands.Context) -> None:
        """Shut down the bot (admin only)

        Args:
            ctx: Command context
        """
        await self.bot.close()
        print("Bot Closed")

    @commands.command(name="동기화", help="슬래시 명령어를 동기화합니다")
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context) -> None:
        """Synchronize slash commands (admin only)"""
        try:
            await self.bot.tree.sync()
            await ctx.send("슬래시 명령어 동기화 완료!")
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["manage_guild"])
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            raise ValueError("명령어 동기화에 실패했습니다") from e

    @commands.command(
        name="버전",
        help="봇의 현재 버전을 확인합니다",
        brief="버전 확인",
        aliases=["version"],
    )
    async def version_prefix(self, ctx: commands.Context) -> None:
        """Show bot version information"""
        await self._handle_version(ctx)

    @discord.app_commands.command(
        name="version",
        description="봇의 현재 버전을 확인합니다"
    )
    async def version_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for version"""
        await self._handle_version(interaction)

    async def _handle_version(self, ctx_or_interaction: CommandContext) -> None:
        """Handle version command
        
        Args:
            ctx_or_interaction: Command context or interaction
        """
        version_info = self.bot.version_info
        embed = discord.Embed(
            title="🤖 봇 버전 정보",
            description=(
                f"**버전:** {version_info.version}\n"
                f"**커밋:** {version_info.commit}\n"
                f"**브랜치:** {version_info.branch}"
            ),
            color=INFO_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed)
