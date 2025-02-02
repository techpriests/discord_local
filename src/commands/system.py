import logging
from typing import Union

import discord
from discord.ext import commands

from ..utils.decorators import command_handler
from .base_commands import BaseCommands

# Constants for embed colors
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
INFO_COLOR = discord.Color.blue()

logger = logging.getLogger(__name__)


class SystemCommands(BaseCommands):
    """System-related commands for bot management"""

    def __init__(self, bot: commands.Bot):
        """Initialize system commands

        Args:
            bot: Discord bot instance
        """
        self._bot = bot

    @property
    def bot(self) -> commands.Bot:
        return self._bot

    @command_handler()
    async def _handle_ping(
        self, ctx_or_interaction: Union[commands.Context, discord.Interaction]
    ) -> None:
        """Handle ping command to check bot latency"""
        try:
            embed = discord.Embed(title="🏓 퐁!", color=INFO_COLOR)
            embed.add_field(name="지연시간", value=f"{round(self.bot.latency * 1000)}ms")
            await self.send_response(ctx_or_interaction, embed=embed)
        except Exception as e:
            logger.error(f"Error in ping command: {e}")
            embed = discord.Embed(
                title="❌ 오류",
                description="지연시간을 측정하는데 실패했습니다.",
                color=ERROR_COLOR,
            )
            await self.send_response(ctx_or_interaction, embed=embed)

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
    async def sync(self, ctx):
        """Synchronize slash commands (admin only)

        Args:
            ctx: Command context

        Raises:
            commands.MissingPermissions: If user is not an administrator
            discord.Forbidden: If bot lacks required permissions
        """
        try:
            await self.bot.tree.sync()
            await ctx.send("슬래시 명령어 동기화 완료!")
        except discord.Forbidden as e:
            logger.error(f"Permission error in sync command: {e}")
            raise discord.Forbidden("동기화 권한이 없습니다") from e
        except Exception as e:
            logger.error(f"Error syncing commands: {e}")
            raise ValueError("명령어 동기화에 실패했습니다") from e
