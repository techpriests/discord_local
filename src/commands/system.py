import logging
from typing import Union, Optional

import discord
from discord.ext import commands
from discord import app_commands

from src.utils.decorators import command_handler
from src.utils.types import CommandContext
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
        try:
            await ctx.send("봇을 종료합니다...")
            await self.bot.close()
        except Exception as e:
            logger.error(f"Error during bot shutdown: {e}")
            await ctx.send("봇 종료 중 오류가 발생했습니다.")

    @commands.command(aliases=["restart"])
    @commands.has_permissions(administrator=True)
    async def reboot(self, ctx: commands.Context) -> None:
        """Restart the bot (admin only)

        Args:
            ctx: Command context
        """
        try:
            await ctx.send("봇을 재시작합니다...")
            await self.bot.close()
            # The Docker container's restart policy will handle the actual restart
        except Exception as e:
            logger.error(f"Error during bot restart: {e}")
            await ctx.send("봇 재시작 중 오류가 발생했습니다.")

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

    @commands.command(
        name="help",
        help="봇의 도움말을 보여줍니다",
        brief="도움말 보기",
        aliases=["pthelp", "도움말", "도움", "명령어"],
        description="봇의 모든 명령어와 사용법을 보여줍니다.\n"
        "사용법:\n"
        "• !!help\n"
        "• 프틸 help\n"
        "• pt help"
    )
    async def help_prefix(self, ctx: commands.Context) -> None:
        """Show help information"""
        await self._handle_help(ctx)

    @app_commands.command(name="help", description="봇의 도움말을 보여줍니다")
    async def help_slash(self, interaction: discord.Interaction) -> None:
        """Show help information"""
        await self._handle_help(interaction)

    async def _handle_help(self, ctx_or_interaction: CommandContext) -> None:
        """Handle help command for both prefix and slash commands
        
        Args:
            ctx_or_interaction: Command context or interaction
        """
        try:
            # Create help embed
            embed = discord.Embed(
                title="🤖 프틸롭시스 도움말",
                description=(
                    "프틸롭시스는 다양한 기능을 제공하는 디스코드 봇입니다.\n"
                    "모든 명령어는 다음 세 가지 방식으로 사용할 수 있습니다:\n\n"
                    "1. !!명령어 - 기본 접두사\n"
                    "2. 프틸 명령어 - 한글 접두사\n"
                    "3. pt command - 영문 접두사\n"
                    "4. /command - 슬래시 명령어"
                ),
                color=discord.Color.blue()
            )

            # Add command categories
            embed.add_field(
                name="🎮 엔터테인먼트",
                value=(
                    "• !!안녕 - 봇과 인사하기\n"
                    "• !!주사위 [XdY] - 주사위 굴리기 (예: 2d6)\n"
                    "• !!투표 [선택지1] [선택지2] ... - 투표 생성\n"
                    "• !!골라줘 [선택지1] [선택지2] ... - 무작위 선택"
                ),
                inline=False
            )

            embed.add_field(
                name="🤖 AI 명령어",
                value=(
                    "• !!대화 [메시지] - AI와 대화하기\n"
                    "• !!대화종료 - 대화 세션 종료\n"
                    "• !!사용량 - AI 시스템 상태 확인"
                ),
                inline=False
            )

            embed.add_field(
                name="📊 정보 명령어",
                value=(
                    "• !!스팀 [게임이름] - 스팀 게임 정보 확인\n"
                    "• !!시간 [지역] - 세계 시간 확인\n"
                    "• !!인구 [국가] - 국가 인구 정보 확인\n"
                    "• !!환율 [통화코드] - 환율 정보 확인"
                ),
                inline=False
            )

            embed.add_field(
                name="⚙️ 시스템 명령어",
                value=(
                    "• !!핑 - 봇 지연시간 확인\n"
                    "• !!복사 [메시지] - 메시지 복사\n"
                    "• !!동기화 - 슬래시 명령어 동기화 (관리자 전용)"
                ),
                inline=False
            )

            embed.add_field(
                name="💾 메모리 명령어",
                value=(
                    "• !!기억 [텍스트] [별명] - 정보 저장\n"
                    "• !!알려 [별명] - 정보 확인\n"
                    "• !!잊어 [별명] - 정보 삭제"
                ),
                inline=False
            )

            # Add footer with version info
            embed.set_footer(text=f"버전: {self.bot.version_info.version} | {self.bot.version_info.commit[:7]}")

            # Send help message
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=embed)
                else:
                    await ctx_or_interaction.response.send_message(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in help command: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ 오류",
                description="도움말을 표시하는 중 오류가 발생했습니다.",
                color=discord.Color.red()
            )
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=error_embed)
                else:
                    await ctx_or_interaction.response.send_message(embed=error_embed)
            else:
                await ctx_or_interaction.send(embed=error_embed)
