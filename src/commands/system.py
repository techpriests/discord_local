import logging
import os
import time
import asyncio
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import zipfile

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
            raise ValueError("지연시간을 측정할 수 없어")

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
            raise ValueError("메시지를 복사할 수가 없네")

    @commands.command(
        name="따라해",
        help="메시지를 따라합니다",
        brief="메시지 따라하기",
        aliases=["copy", "mimic"],
        description=(
            "입력한 메시지를 그대로 따라합니다.\n"
            "사용법: 뮤 따라해 [메시지]\n"
            "예시: 뮤 따라해 안녕하세요"
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
            raise discord.Forbidden("메시지를 삭제할 권한이 없어") from e
        except Exception as e:
            logger.error(f"Error in copy_message: {e}")
            raise ValueError("메시지를 복사하다가 문제가 생겼어") from e

    @commands.command(
        name="로그업로드",
        help="현재 봇 로그 파일(bot.log)을 채널에 업로드합니다 (봇 소유자 전용)",
        hidden=True,
        aliases=["logupload", "업로그"]
    )
    @commands.is_owner()
    async def upload_logs_prefix(self, ctx: commands.Context) -> None:
        """Upload the current bot log file to the invoking channel (admin only)"""
        try:
            base_dir = Path(__file__).parents[2]
            log_path = base_dir / "bot.log"

            if not log_path.exists():
                await ctx.send("음... 로그 파일을 찾을 수 없어. bot.log가 아직 생성되지 않았을 수도 있어.")
                return

            max_size_bytes = 8 * 1024 * 1024  # ~8MB typical upload limit

            if log_path.stat().st_size <= max_size_bytes:
                await ctx.send(
                    content="📦 현재 로그 파일을 업로드할게.",
                    file=discord.File(fp=str(log_path), filename="bot.log")
                )
                return

            # Compress to ZIP if too large
            zip_path = base_dir / "bot.log.zip"
            try:
                with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(log_path, arcname="bot.log")
            except Exception as e:
                logger.error(f"Failed to zip log file: {e}", exc_info=True)
                await ctx.send("로그 파일 압축에 실패했어. 잠시 후 다시 시도해줘.")
                return

            try:
                if zip_path.stat().st_size <= max_size_bytes:
                    await ctx.send(
                        content="📦 로그 파일이 커서 압축해서 보낼게.",
                        file=discord.File(fp=str(zip_path), filename="bot.log.zip")
                    )
                    return
            finally:
                # Clean up the zip regardless of outcome after sending/size check
                try:
                    if zip_path.exists():
                        os.remove(zip_path)
                except Exception:
                    pass

            # As a fallback, send the last ~2MB of the log
            tail_bytes = 2 * 1024 * 1024
            tail_path = base_dir / "bot_tail.log"
            try:
                with open(log_path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    file_size = f.tell()
                    start_pos = max(0, file_size - tail_bytes)
                    f.seek(start_pos)
                    data = f.read()
                with open(tail_path, "wb") as out:
                    out.write(data)

                await ctx.send(
                    content="⚠️ 로그 파일이 너무 커서 마지막 일부만 보낼게 (약 2MB).",
                    file=discord.File(fp=str(tail_path), filename="bot_tail.log")
                )
            finally:
                try:
                    if tail_path.exists():
                        os.remove(tail_path)
                except Exception:
                    pass
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["attach_files", "send_messages"])
        except Exception as e:
            logger.error(f"Failed to upload logs: {e}", exc_info=True)
            await ctx.send(f"로그 업로드 중 문제가 발생했어: {type(e).__name__}: {str(e)}")

    @app_commands.command(name="upload_logs", description="현재 봇 로그 파일을 업로드합니다 (봇 소유자 전용)")
    @app_commands.check(lambda i: i.client.is_owner(i.user))
    async def upload_logs_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to upload the current bot log file (admin only)"""
        try:
            base_dir = Path(__file__).parents[2]
            log_path = base_dir / "bot.log"

            if not log_path.exists():
                await interaction.response.send_message("음... 로그 파일을 찾을 수 없어. bot.log가 아직 생성되지 않았을 수도 있어.")
                return

            max_size_bytes = 8 * 1024 * 1024

            if log_path.stat().st_size <= max_size_bytes:
                await interaction.response.send_message(
                    content="📦 현재 로그 파일을 업로드할게.",
                    file=discord.File(fp=str(log_path), filename="bot.log")
                )
                return

            # Compress to ZIP if too large
            zip_path = base_dir / "bot.log.zip"
            try:
                with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(log_path, arcname="bot.log")
            except Exception as e:
                logger.error(f"Failed to zip log file: {e}", exc_info=True)
                await interaction.response.send_message("로그 파일 압축에 실패했어. 잠시 후 다시 시도해줘.")
                return

            try:
                if zip_path.stat().st_size <= max_size_bytes:
                    await interaction.response.send_message(
                        content="📦 로그 파일이 커서 압축해서 보낼게.",
                        file=discord.File(fp=str(zip_path), filename="bot.log.zip")
                    )
                    return
            finally:
                try:
                    if zip_path.exists():
                        os.remove(zip_path)
                except Exception:
                    pass

            # Fallback: send last ~2MB
            tail_bytes = 2 * 1024 * 1024
            tail_path = base_dir / "bot_tail.log"
            try:
                with open(log_path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    file_size = f.tell()
                    start_pos = max(0, file_size - tail_bytes)
                    f.seek(start_pos)
                    data = f.read()
                with open(tail_path, "wb") as out:
                    out.write(data)

                await interaction.response.send_message(
                    content="⚠️ 로그 파일이 너무 커서 마지막 일부만 보낼게 (약 2MB).",
                    file=discord.File(fp=str(tail_path), filename="bot_tail.log")
                )
            finally:
                try:
                    if tail_path.exists():
                        os.remove(tail_path)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to upload logs (slash): {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(f"로그 업로드 중 문제가 발생했어: {type(e).__name__}: {str(e)}")
            else:
                await interaction.response.send_message(f"로그 업로드 중 문제가 발생했어: {type(e).__name__}: {str(e)}")

    @commands.command(aliases=["quit"])
    @commands.has_permissions(administrator=True)
    async def close(self, ctx: commands.Context) -> None:
        """Shut down the bot (admin only)

        Args:
            ctx: Command context
        """
        try:
            await ctx.send("봇을 종료할게...")
            await self.bot.close()
        except Exception as e:
            logger.error(f"Error during bot shutdown: {e}")
            await ctx.send("봇 종료 중 문제가 생겼어.")

    @commands.command(aliases=["restart"])
    @commands.has_permissions(administrator=True)
    async def reboot(self, ctx: commands.Context) -> None:
        """Restart the bot (admin only)

        Args:
            ctx: Command context
        """
        try:
            await ctx.send("봇을 재시작할게...")
            
            # Schedule force exit after a timeout
            import threading
            import os
            import signal
            import time
            
            def force_exit_after_timeout():
                # Wait 10 seconds for graceful shutdown
                time.sleep(10)
                # If we're still running after timeout, force exit
                logger.warning("Shutdown timeout reached. Forcing exit...")
                os.kill(os.getpid(), signal.SIGTERM)
            
            # Start force exit timer in a non-blocking thread
            threading.Thread(target=force_exit_after_timeout, daemon=True).start()
            
            # Initiate graceful shutdown
            await self.bot.close()
            # The Docker container's restart policy will handle the actual restart
        except Exception as e:
            logger.error(f"Error during bot restart: {e}")
            await ctx.send("재시작 중에 문제가 생겼어.")

    @commands.command(name="동기화", help="슬래시 명령어를 동기화합니다")
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context) -> None:
        """Synchronize slash commands (admin only)"""
        try:
            await self.bot.tree.sync()
            await ctx.send("명령어 동기화 완료했어!")
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["manage_guild"])
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            raise ValueError("명령어 동기화 중중 문제가 생겼어") from e

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
        aliases=["muhelp", "도움말", "도움", "명령어"],
        description="봇의 모든 명령어와 사용법을 보여줍니다.\n"
        "사용법:\n"
        "• 뮤 도움말\n"
        "• 뮤 help\n"
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
                title="🤖 뮤엘시스 도움말",
                description=(
                    "모든 명령어는 다음 세 가지 방식으로 사용할 수 있어:\n\n"
                    "1. 뮤 명령어 - 기본 접두사\n"
                    "2. mu command - 영문 접두사\n"
                    "3. /command - 슬래시 명령어"
                ),
                color=discord.Color.blue()
            )

            # Add command categories
            embed.add_field(
                name="🎮 엔터테인먼트",
                value=(
                    "• 뮤 안녕 - 봇과 인사하기\n"
                    "• 뮤 주사위 [XdY] - 주사위 굴리기 (예: 2d6)\n"
                    "• 뮤 투표 [선택지1] [선택지2] ... - 투표 생성\n"
                    "• 뮤 골라줘 [선택지1] [선택지2] ... - 무작위 선택"
                ),
                inline=False
            )

            embed.add_field(
                name="🤖 AI 명령어",
                value=(
                    "• 뮤 대화 [메시지] - AI와 대화하기\n"
                    "• 뮤 알려줘 [메시지] - AI와 대화하기\n"
                    "• 뮤 대화종료 - 대화 세션 종료\n"
                    "• 뮤 사용량 - AI 시스템 상태 확인"
                ),
                inline=False
            )

            embed.add_field(
                name="📊 정보 명령어",
                value=(
                    "• 뮤 스팀 [게임이름] - 스팀 게임 정보 확인\n"
                    "• 뮤 시간 [지역] - 세계 시간 확인\n"
                    "• 뮤 인구 [국가] - 국가 인구 정보 확인\n"
                    "• 뮤 환율 [통화코드] - 환율 정보 확인(현재 사용 불가)"
                ),
                inline=False
            )

            embed.add_field(
                name="🎲 명일방주 명령어",
                value=(
                    "• 뮤 명방 [횟수] - 일반 배너 뽑기 확률 계산\n"
                    "  └ /arknights_pull [횟수] - 슬래시 명령어 버전\n"
                    "• 뮤 명방한정 [횟수] - 한정 배너 뽑기 확률 계산\n"
                    "• 뮤 자원 [합성옥] [순오리지늄] [헤드헌팅권] - 보유 자원으로 가능한 뽑기 횟수 계산\n"
                    "  └ /arknights_resources - 슬래시 명령어 버전"
                ),
                inline=False
            )

            embed.add_field(
                name="⚙️ 시스템 명령어",
                value=(
                    "• 뮤 핑 - 봇 지연시간 확인\n"
                    "• 뮤 복사 [메시지] - 메시지 복사\n"
                ),
                inline=False
            )

            embed.add_field(
                name="💾 메모리 명령어[현재 사용불가]",
                value=(
                    "• 뮤 기억 [텍스트] [별명] - 정보 저장\n"
                    "• 뮤 알려 [별명] - 정보 확인\n"
                    "• 뮤 잊어 [별명] - 정보 삭제"
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
                description="도움말을 표시하는 중에 문제가 생겼어.",
                color=discord.Color.red()
            )
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=error_embed)
                else:
                    await ctx_or_interaction.response.send_message(embed=error_embed)
            else:
                await ctx_or_interaction.send(embed=error_embed)

    @commands.command(name="업데이트확인", help="새 업데이트 확인")
    @commands.has_permissions(administrator=True)
    async def update_check_prefix(self, ctx: commands.Context) -> None:
        """Check for updates (admin only)"""
        try:
            import os
            from pathlib import Path
            
            update_file = os.path.join(Path(__file__).parents[2], "updates.txt")
            
            if os.path.exists(update_file):
                with open(update_file, 'r') as f:
                    update_info = f.read().strip()
                
                # Filter out any personal information and format securely
                filtered_info = self._filter_update_info(update_info)
                
                # Send notification with reload instructions
                await ctx.send(f"**업데이트가 준비되었어**\n```\n{filtered_info}\n```\n적용하려면 `뮤 리로드` 명령어를 사용해줘.")
            else:
                await ctx.send("새 업데이트가 없어.")
        except Exception as e:
            logger.error(f"Failed to check updates: {e}")
            await ctx.send(f"업데이트 확인 중 오류가 발생했어. 오류: {str(e)}")

    @discord.app_commands.command(
        name="update_check",
        description="새 업데이트를 확인합니다"
    )
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def update_check_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for update check"""
        try:
            import os
            from pathlib import Path
            
            update_file = os.path.join(Path(__file__).parents[2], "updates.txt")
            
            if os.path.exists(update_file):
                with open(update_file, 'r') as f:
                    update_info = f.read().strip()
                
                # Filter out any personal information and format securely
                filtered_info = self._filter_update_info(update_info)
                
                # Send notification with reload instructions
                await interaction.response.send_message(
                    f"**업데이트가 준비되었어**\n```\n{filtered_info}\n```\n적용하려면 `뮤 리로드` 명령어를 사용해줘."
                )
            else:
                await interaction.response.send_message("새 업데이트가 없어.")
        except Exception as e:
            logger.error(f"Failed to check updates: {e}")
            await interaction.response.send_message(f"업데이트 확인 중 오류가 발생했어. 오류: {str(e)}")
    
    def _filter_update_info(self, update_info: str) -> str:
        """Filter sensitive information from update info
        
        Args:
            update_info: Raw update info from file
            
        Returns:
            str: Filtered update info
        """
        import re
        lines = update_info.split('\n')
        filtered_lines = []
        
        for line in lines:
            # Only keep time info and commit message
            if line.startswith("Hot reload updates available") or line.startswith("Commit message:"):
                filtered_lines.append(line)
            # Remove any personal identifiers
            elif not line.startswith("Changes by:"):
                # Check for any email-like patterns and remove them
                line = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL REMOVED]', line)
                # Remove GitHub usernames
                line = re.sub(r'@[A-Za-z0-9_-]+', '@[USERNAME]', line)
                filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)
    
    @commands.command(name="리로드", help="명령어 모듈을 다시 로드합니다")
    @commands.has_permissions(administrator=True)
    async def reload_prefix(self, ctx: commands.Context, module: Optional[str] = None) -> None:
        """Reload command modules (admin only)"""
        try:
            # Track reload outcomes
            success_modules = []
            failed_modules = {}
            
            # Import the reload function
            import importlib
            import sys
            
            if module:
                # Reload specific module
                found = False
                for cmd_class in self.bot._command_classes:
                    if cmd_class.__name__.lower() == module.lower():
                        found = True
                        cog_name = cmd_class.__name__
                        
                        try:
                            # Remove existing cog
                            if self.bot.get_cog(cog_name):
                                await self.bot.remove_cog(cog_name)
                            
                            # Get module name from class
                            module_name = cmd_class.__module__
                            
                            # Force reload the module
                            if module_name in sys.modules:
                                logger.info(f"Reloading module: {module_name}")
                                importlib.reload(sys.modules[module_name])
                            
                            # Re-import the command class
                            module_obj = importlib.import_module(module_name)
                            cmd_class = getattr(module_obj, cog_name)
                            
                            # Re-initialize and add the cog
                            if cog_name == "InformationCommands":
                                cog = cmd_class(self.bot.api_service)
                            elif cog_name == "SystemCommands":
                                cog = cmd_class(self.bot)
                            elif cog_name == "AICommands":
                                cog = cmd_class()
                                cog.bot = self.bot
                            elif cog_name == "TeamDraftCommands":
                                cog = cmd_class(self.bot)  # Pass bot as constructor parameter
                            else:
                                cog = cmd_class()
                                
                            await self.bot.add_cog(cog)
                            success_modules.append(cog_name)
                        except Exception as e:
                            logger.error(f"Failed to reload {cog_name}: {e}", exc_info=True)
                            failed_modules[cog_name] = str(e)
                        
                        break
                
                if not found:
                    await ctx.send(f"모듈 '{module}'을(를) 찾을 수 없어.")
                    return
            else:
                # Reload all modules
                for cmd_class in self.bot._command_classes:
                    cog_name = cmd_class.__name__
                    try:
                        # Remove existing cog
                        if self.bot.get_cog(cog_name):
                            await self.bot.remove_cog(cog_name)
                        
                        # Get module name from class
                        module_name = cmd_class.__module__
                        
                        # Force reload the module
                        if module_name in sys.modules:
                            logger.info(f"Reloading module: {module_name}")
                            importlib.reload(sys.modules[module_name])
                        
                        # Re-import the command class to get updated version
                        module_obj = importlib.import_module(module_name)
                        cmd_class = getattr(module_obj, cog_name)
                        
                        # Re-initialize and add the cog with specific initialization
                        if cog_name == "InformationCommands":
                            cog = cmd_class(self.bot.api_service)
                        elif cog_name == "SystemCommands":
                            cog = cmd_class(self.bot)
                        elif cog_name == "AICommands":
                            cog = cmd_class()
                            cog.bot = self.bot
                        elif cog_name == "TeamDraftCommands":
                            cog = cmd_class(self.bot)  # Pass bot as constructor parameter
                        elif cog_name == "FateReplayCommands":
                            cog = cmd_class(self.bot)
                        else:
                            cog = cmd_class()
                            
                        await self.bot.add_cog(cog)
                        success_modules.append(cog_name)
                    except Exception as e:
                        logger.error(f"Failed to reload {cog_name}: {e}", exc_info=True)
                        failed_modules[cog_name] = str(e)
            
            # Try to sync slash commands (but don't fail if it doesn't work)
            try:
                await self.bot.tree.sync()
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")
                failed_modules["CommandSync"] = str(e)
            
            # Clear update notification if exists
            import os
            from pathlib import Path
            
            update_file = os.path.join(Path(__file__).parents[2], "updates.txt")
            update_info = None
            if os.path.exists(update_file):
                with open(update_file, 'r') as f:
                    update_info = f.read().strip()
                os.remove(update_file)
                await ctx.send("업데이트가 성공적으로 적용되었어.")
            
            # Update version info if hot reload version file exists
            hot_reload_version_file = os.path.join(Path(__file__).parents[2], "hot_reload_version.txt")
            if os.path.exists(hot_reload_version_file):
                try:
                    with open(hot_reload_version_file, 'r') as f:
                        new_commit = f.read().strip()
                    
                    # Only update if we have a valid commit hash
                    if new_commit and len(new_commit) >= 7:
                        # Create a new VersionInfo with updated commit
                        from src.utils.version import VersionInfo
                        self.bot.version_info = VersionInfo(
                            version=self.bot.version_info.version,
                            commit=new_commit[:7],  # Use first 7 chars of commit hash
                            branch=self.bot.version_info.branch
                        )
                        
                        # Update bot presence with new commit info
                        await self.bot.change_presence(
                            activity=discord.Game(
                                name=f"뮤 도움말 | /help | {self.bot.version_info.commit}"
                            )
                        )
                        
                        logger.info(f"Version info updated to: {self.bot.version_info.commit}")
                except Exception as e:
                    logger.error(f"Failed to update version info: {e}")
            
            # Send detailed report
            if success_modules and not failed_modules:
                # All modules reloaded successfully
                modules_str = ", ".join(success_modules)
                await ctx.send(f"✅ 모든 모듈이 성공적으로 리로드됐어: {modules_str}")
            elif success_modules and failed_modules:
                # Some modules failed, some succeeded
                success_str = ", ".join(success_modules)
                failed_str = ", ".join(failed_modules.keys())
                
                # Just show a summary instead of detailed errors
                await ctx.send(f"⚠️ 일부 모듈만 리로드됐어.\n✅ 성공: {success_str}\n❌ 실패: {failed_str}")
            else:
                # All modules failed
                failed_str = ", ".join(failed_modules.keys())
                await ctx.send(f"❌ 모든 모듈 리로드에 실패했어. 실패한 모듈: {failed_str}")
            
        except Exception as e:
            logger.error(f"Failed to reload modules: {e}", exc_info=True)
            await ctx.send(f"모듈 리로드 중 오류가 발생했어: {str(e)}")
            
    @discord.app_commands.command(
        name="reload",
        description="명령어 모듈을 다시 로드합니다"
    )
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def reload_slash(self, interaction: discord.Interaction, module: Optional[str] = None) -> None:
        """Slash command for reload"""
        ctx = await commands.Context.from_interaction(interaction)
        await self.reload_prefix(ctx, module)
        
    @commands.command(name="롤백", help="이전 버전으로 롤백합니다")
    @commands.has_permissions(administrator=True)
    async def rollback(self, ctx: commands.Context) -> None:
        """Rollback to previous version (admin only)"""
        from datetime import datetime, timedelta
        import os, shutil
        from pathlib import Path
        
        # Define paths
        base_dir = Path(__file__).parents[2]
        lock_file = base_dir / "rollback.lock"
        backup_info_file = base_dir / "current_backup.txt"
        temp_restore_dir = None
        
        try:
            # Check for concurrent operations
            if lock_file.exists():
                try:
                    last_modified = datetime.fromtimestamp(lock_file.stat().st_mtime)
                    if datetime.now() - last_modified < timedelta(minutes=10):
                        await ctx.send("⚠️ 응? 이미 다른 롤백이나 업데이트 작업이 진행 중인데? 조금만 기다려줘.")
                        return
                    # Lock file exists but old (>10 min), assume stale and continue
                    logger.warning("Removing stale rollback lock file")
                except Exception as e:
                    logger.error(f"Error checking lock file: {e}")
            
            # Create lock file
            with open(lock_file, "w") as f:
                f.write(f"Rollback started by {ctx.author} at {datetime.now().isoformat()}")
            
            # Check for deployment lock
            deployment_lock = base_dir / "update.lock"
            if deployment_lock.exists():
                try:
                    last_modified = datetime.fromtimestamp(deployment_lock.stat().st_mtime)
                    if datetime.now() - last_modified < timedelta(minutes=5):
                        await ctx.send("⚠️ 지금 배포 작업이 진행 중이야! 조금만 더 기다려줘.")
                        return
                except Exception:
                    pass  # Continue if we can't check the file
            
            # Check for current backup info
            if not backup_info_file.exists():
                await ctx.send("음... 롤백할 백업 정보가 없는데? 백업부터 해야 되는 거 아닌가?")
                return
                
            # Read backup timestamp
            with open(backup_info_file, 'r') as f:
                backup_timestamp = f.read().strip()
                
            backup_dir = base_dir / f"src_backup_{backup_timestamp}"
            
            if not backup_dir.exists():
                await ctx.send(f"이상한데? 백업 디렉토리를 찾을 수 없어: {backup_dir}. 이전 실험 기록이 사라진 것 같네.")
                return
            
            # Verify backup integrity
            integrity_verified = False
            verification_message = None
            try:
                # Check file count if available
                count_file = backup_dir / "file_count.txt"
                if count_file.exists():
                    with open(count_file, 'r') as f:
                        expected_count = int(f.read().strip())
                    
                    actual_count = 0
                    for root, _, files in os.walk(backup_dir):
                        actual_count += sum(1 for f in files if f.endswith('.py'))
                    
                    if actual_count < expected_count * 0.9:  # Allow 10% leeway
                        verification_message = f"⚠️ 흠... 백업이 완전하지 않은 것 같은데? 예상 파일: {expected_count}개, 실제로 있는 파일: {actual_count}개."
                    else:
                        integrity_verified = True
            except Exception as e:
                logger.error(f"Error verifying backup integrity: {e}")
                verification_message = "⚠️ 백업 무결성 검증이 안 되네? 뭔가 이상한데... 그래도 계속할래?"
            
            # Confirm with user, including integrity warning if any
            confirm_message = f"**{backup_timestamp}** 백업으로 롤백할까? 계속하려면 10초 안에 👍 반응을 추가해줘!"
            if verification_message:
                confirm_message = f"{verification_message}\n{confirm_message}"
                
            confirm_msg = await ctx.send(confirm_message)
            
            # Add confirmation reaction
            await confirm_msg.add_reaction("👍")
            
            def check(reaction, user):
                return (
                    user == ctx.author 
                    and str(reaction.emoji) == "👍" 
                    and reaction.message.id == confirm_msg.id
                )
            
            try:
                # Wait for confirmation
                await self.bot.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("롤백이 취소됐어. 현재 상태가 더 좋을지도 모르니까.")
                return
                
            # Perform rollback
            await ctx.send("롤백 진행 중... 이전 버전으로 돌아가는 중이야. 잠시만 기다려줘!")
            
            # Create temp directory for staged restore
            temp_restore_dir = base_dir / f"temp_restore_{int(time.time())}"
            os.makedirs(temp_restore_dir, exist_ok=True)
            
            # Create directories in temp location
            temp_commands_dir = temp_restore_dir / "commands"
            temp_services_dir = temp_restore_dir / "services"
            temp_utils_dir = temp_restore_dir / "utils"
            
            os.makedirs(temp_commands_dir, exist_ok=True)
            os.makedirs(temp_services_dir, exist_ok=True)
            os.makedirs(temp_utils_dir, exist_ok=True)
            
            # First copy backup files to temporary location
            backup_commands = backup_dir / "commands"
            backup_services = backup_dir / "services"
            backup_utils = backup_dir / "utils"
            
            # Copy files to temp directory first using shutil
            if backup_commands.exists():
                for item in os.listdir(backup_commands):
                    src_item = backup_commands / item
                    dst_item = temp_commands_dir / item
                    if src_item.is_dir():
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            
            if backup_services.exists():
                for item in os.listdir(backup_services):
                    src_item = backup_services / item
                    dst_item = temp_services_dir / item
                    if src_item.is_dir():
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            
            if backup_utils.exists():
                for item in os.listdir(backup_utils):
                    src_item = backup_utils / item
                    dst_item = temp_utils_dir / item
                    if src_item.is_dir():
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            
            # Verify the temp restore contains files
            temp_file_count = 0
            for root, _, files in os.walk(temp_restore_dir):
                temp_file_count += len(files)
            
            if temp_file_count == 0:
                await ctx.send("⚠️ 임시 복원 디렉토리에 파일이 하나도 없어. 롤백을 취소할게.")
                return
            
            # If verification passed, copy from temp to actual src dirs
            src_dir = base_dir / "src"
            src_commands_dir = src_dir / "commands"
            src_services_dir = src_dir / "services"
            src_utils_dir = src_dir / "utils"
            
            # Now copy from temp to actual src with shutil
            for item in os.listdir(temp_commands_dir):
                src_item = temp_commands_dir / item
                dst_item = src_commands_dir / item
                if src_item.is_dir():
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            for item in os.listdir(temp_services_dir):
                src_item = temp_services_dir / item
                dst_item = src_services_dir / item
                if src_item.is_dir():
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            for item in os.listdir(temp_utils_dir):
                src_item = temp_utils_dir / item
                dst_item = src_utils_dir / item
                if src_item.is_dir():
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            # Now reload all modules
            reload_success = True
            reload_errors = []
            
            for cmd_class in self.bot._command_classes:
                try:
                    cog_name = cmd_class.__name__
                    if self.bot.get_cog(cog_name):
                        await self.bot.remove_cog(cog_name)
                except Exception as e:
                    reload_success = False
                    reload_errors.append(f"{cmd_class.__name__}: {str(e)}")
            
            # Re-register all commands
            try:
                # Use same method as reload command for consistency
                await self.reload_prefix(ctx)
            except Exception as e:
                reload_success = False
                reload_errors.append(f"Command registration: {str(e)}")
            
            # Delete the hot reload version file if it exists
            hot_reload_version_file = base_dir / "hot_reload_version.txt"
            if hot_reload_version_file.exists():
                os.remove(hot_reload_version_file)
            
            # Remove current backup marker only if reload succeeded
            if reload_success:
                os.remove(backup_info_file)
                await ctx.send(f"**{backup_timestamp}** 백업으로 롤백 완료! 모든 명령어가 다시 로드됐어.")
            else:
                error_details = "\n".join(reload_errors[:5])  # Show first 5 errors
                await ctx.send(f"⚠️ 흠, 이상한데? 파일은 복원됐지만 일부 모듈이 제대로 로드되지 않았어:\n```{error_details}```\n문제가 계속되면 완전히 재시작해야 할 것 같아.")
            
        except Exception as e:
            logger.error(f"Failed to rollback: {e}", exc_info=True)
            await ctx.send(f"롤백 도중에 문제가 생겼어. 오류: {str(e)}")
        finally:
            # Cleanup temp directory
            if temp_restore_dir and temp_restore_dir.exists():
                try:
                    shutil.rmtree(temp_restore_dir)
                except Exception as e:
                    logger.error(f"Failed to remove temp directory: {e}")
            
            # Always remove lock file
            try:
                if lock_file.exists():
                    os.remove(lock_file)
            except Exception as e:
                logger.error(f"Failed to remove lock file: {e}")
    
    @commands.command(name="백업확인", help="사용 가능한 백업 확인")
    @commands.has_permissions(administrator=True)
    async def check_backups(self, ctx: commands.Context) -> None:
        """Check available backups (admin only)"""
        try:
            from pathlib import Path
            
            base_dir = Path(__file__).parents[2]
            
            # List all backup directories
            backup_dirs = [d for d in os.listdir(base_dir) if d.startswith("src_backup_")]
            
            if not backup_dirs:
                await ctx.send("아직 사용할 수 있는 백업이 없어.")
                return
                
            # Sort by timestamp (newest first)
            backup_dirs.sort(reverse=True)
            
            # Format and send message
            backup_list = "\n".join([
                f"{i+1}. {d.replace('src_backup_', '')}" 
                for i, d in enumerate(backup_dirs[:10])  # Show at most 10
            ])
            
            # Check if current_backup.txt exists and read its content
            current_backup = "없음"
            backup_info_file = base_dir / "current_backup.txt"
            if backup_info_file.exists():
                with open(backup_info_file, 'r') as f:
                    current_backup = f.read().strip()
            
            await ctx.send(f"**사용 가능한 백업:**\n```\n{backup_list}\n```\n**현재 롤백 가능한 백업:** {current_backup}")
            
        except Exception as e:
            logger.error(f"Failed to check backups: {e}")
            await ctx.send(f"백업 확인 중에 문제가 생겼어. 오류: {str(e)}")
    
    @commands.command(name="긴급종료", help="긴급 상황에서 봇을 안전하게 종료합니다")
    @commands.has_permissions(administrator=True)
    async def emergency_shutdown(self, ctx: commands.Context, *, reason: str = "긴급 종료 요청") -> None:
        """Emergency shutdown in case of critical failures (admin only)
        
        Args:
            ctx: Command context
            reason: Reason for emergency shutdown
        """
        try:
            # Confirm with user
            confirm_msg = await ctx.send(f"⚠️ **주의! 긴급 종료 프로토콜을 실행할까?**\n"
                                        f"이유: {reason}\n\n"
                                        f"정말로 실험을 멈추려면 👍 반응을 추가해줘. 취소하려면 무시하면 돼!")
            
            await confirm_msg.add_reaction("👍")
            
            def check(reaction, user):
                return (user == ctx.author and 
                        str(reaction.emoji) == "👍" and 
                        reaction.message.id == confirm_msg.id)
            
            try:
                # Wait for confirmation
                await self.bot.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("긴급 종료가 취소됐어.")
                return
            
            # Log the shutdown
            logger.critical(f"EMERGENCY SHUTDOWN triggered by {ctx.author} - Reason: {reason}")
            
            # Final confirmation to owner only
            await ctx.send("⚠️ 장비 종료 중... 다음에 봐!", delete_after=10)
            
            # Schedule shutdown after sending response
            self.bot.loop.call_later(2, self._emergency_exit, reason)
        
        except Exception as e:
            logger.error(f"Failed to execute emergency shutdown: {e}")
            await ctx.send(f"긴급 종료 실행 중에 문제가 생겼어. 오류: {str(e)}")
    
    def _emergency_exit(self, reason: str) -> None:
        """Perform actual shutdown with proper cleanup
        
        Args:
            reason: Shutdown reason for logs
        """
        logger.critical(f"Executing emergency shutdown: {reason}")
        
        try:
            # Try graceful shutdown first
            task = asyncio.create_task(self.bot.close())
            
            # Set a timeout for clean shutdown
            def force_exit():
                logger.critical("Graceful shutdown timed out. Forcing exit.")
                # Force exit
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)
                
            # Force exit after 10 seconds if graceful shutdown doesn't complete
            self.bot.loop.call_later(10, force_exit)
        
        except Exception as e:
            logger.critical(f"Error during emergency shutdown: {e}")
            # Force shutdown as last resort
            import sys
            sys.exit(1)

    @commands.command(name="건강", aliases=["health"])
    @commands.is_owner()  # Restrict to bot owner only
    async def health_check_prefix(self, ctx):
        """Check if all modules are properly loaded after hot-reloading"""
        await self._handle_health_check(ctx)
        
    @discord.app_commands.command(
        name="health",
        description="모듈 핫-리로드 상태를 확인합니다"
    )
    @discord.app_commands.default_permissions(administrator=True)  # Default perm requirement
    @discord.app_commands.check(lambda i: i.client.is_owner(i.user))  # Actual check for owner
    async def health_check_slash(self, interaction: discord.Interaction):
        """Slash command for health check"""
        await self._handle_health_check(interaction)
        
    async def _handle_health_check(self, ctx_or_interaction: CommandContext):
        """Handle health check for both prefix and slash commands"""
        try:
            health_results = []
            
            # Define critical modules to check (add more as needed)
            modules_to_check = [
                {
                    "name": "ClaudeAPI", 
                    "module_path": "src.services.api.claude", 
                    "class_name": "ClaudeAPI",
                    "instance": self.bot.api_service.claude
                }
                # Add other important modules here as needed
            ]
            
            for module_info in modules_to_check:
                # Dynamically import the module
                import importlib
                module = importlib.import_module(module_info["module_path"])
                
                # Get the current class from the module
                current_class = getattr(module, module_info["class_name"])
                
                # Get the instance's class
                instance_class = module_info["instance"].__class__
                
                # Compare the actual class objects
                if current_class is not instance_class:
                    health_results.append(f"❌ {module_info['name']}: Using outdated version")
                else:
                    health_results.append(f"✅ {module_info['name']}: Up to date")
            
            # Overall status
            if all(r.startswith("✅") for r in health_results):
                status = "✅ All systems up to date"
            else:
                status = "❌ Outdated instances detected - restart recommended"
                
            # Send response appropriately for context or interaction
            message = f"**Health Check Results**\n" + "\n".join(health_results) + f"\n\n**Status:** {status}"
            await self.send_response(ctx_or_interaction, message)
            
        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            logger.error(f"Health check error: {error_msg}")
            
            # Send error response appropriately
            message = f"❌ Health check failed with error: {type(e).__name__} - {str(e)}"
            await self.send_response(ctx_or_interaction, message)
