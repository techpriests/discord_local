from discord.ext import commands
import discord
from typing import List
from src.services.memory_db import MemoryDB
import logging
import asyncio
from discord.app_commands import AppCommandError

logger = logging.getLogger(__name__)

class DiscordBot:
    def __init__(self):
        intents = discord.Intents.all()
        self.bot = commands.Bot(command_prefix='!!', intents=intents)
        self.api_service = None
        self.memory_db = MemoryDB()
        
        @self.bot.event
        async def on_ready():
            print(f"{self.bot.user.name} 로그인 성공")
            await self.bot.tree.sync()
            await self.bot.change_presence(status=discord.Status.online, activity=discord.Game('LIVE'))
    
    async def load_cogs(self, cogs: List[commands.Cog], api_service=None):
        """Load cogs asynchronously"""
        self.api_service = api_service
        for cog in cogs:
            await self.bot.add_cog(cog)
    
    async def start(self, token: str):
        """Start the bot"""
        try:
            await self.bot.start(token)
        finally:
            if self.api_service:
                await self.api_service.close()

    @discord.app_commands.command(
        name="exchange",
        description="환율 정보를 보여줍니다"
    )
    async def exchange_slash(self, interaction: discord.Interaction, currency: str = None, amount: float = 1.0):
        """Slash command version"""
        await self._handle_exchange(interaction, currency, amount)

    @commands.command(name='환율', aliases=['exchange'])
    async def exchange_prefix(self, ctx: commands.Context, currency: str = None, amount: float = 1.0):
        """Prefix command version"""
        await self._handle_exchange(ctx, currency, amount)

    async def _handle_exchange(self, ctx_or_interaction, currency: str = None, amount: float = 1.0):
        """Shared handler for both command types"""
        processing_msg = None
        try:
            # Get user name
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            # Send processing message
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)

            # ... exchange rate logic ...
            embed = discord.Embed(...)  # Your existing embed creation

            # Send result and clean up
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.channel.send(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)
                if processing_msg:
                    await processing_msg.delete()

        except Exception as e:
            message = f"환율 정보를 가져오는데 실패했습니다: {str(e)}"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()

    @discord.app_commands.command(
        name="remember",
        description="정보를 기억합니다"
    )
    async def remember_slash(self, interaction: discord.Interaction, text: str, nickname: str):
        """Slash command version"""
        await self._handle_remember(interaction, text, nickname)

    @commands.command(name='기억')
    async def remember_prefix(self, ctx: commands.Context, text: str, nickname: str):
        """Prefix command version"""
        await self._handle_remember(ctx, text, nickname)

    async def _handle_remember(self, ctx_or_interaction, text: str, nickname: str):
        processing_msg = None
        try:
            # Get user name
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
                author = str(ctx_or_interaction.user)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)
                author = str(ctx_or_interaction.author)

            if self.memory_db.remember(text, nickname, author):
                result = f"기억했습니다: {text} → {nickname}"
            else:
                result = "기억하는데 실패했습니다."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.channel.send(result)
            else:
                await ctx_or_interaction.send(result)
                if processing_msg:
                    await processing_msg.delete()

        except Exception as e:
            message = "올바른 형식으로 입력해주세요"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()

    @discord.app_commands.command(
        name="recall",
        description="정보를 알려줍니다"
    )
    async def recall_slash(self, interaction: discord.Interaction, nickname: str):
        """Slash command version"""
        await self._handle_recall(interaction, nickname)

    @commands.command(name='알려')
    async def recall_prefix(self, ctx: commands.Context, nickname: str):
        """Prefix command version"""
        await self._handle_recall(ctx, nickname)

    async def _handle_recall(self, ctx_or_interaction, nickname: str):
        processing_msg = None
        try:
            # Get user name
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)

            memories = self.memory_db.recall(nickname)
            if memories:
                embed = discord.Embed(
                    title=f"{nickname}의 정보",
                    color=discord.Color.blue()
                )
                
                for memory in memories.values():
                    embed.add_field(
                        name=memory['text'],
                        value=f"입력: {memory['author']}\n시간: {memory['timestamp']}",
                        inline=False
                    )
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.channel.send(embed=embed)
                else:
                    await ctx_or_interaction.send(embed=embed)
                    if processing_msg:
                        await processing_msg.delete()
            else:
                message = f"'{nickname}'에 대한 기억이 없습니다."
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.channel.send(message)
                else:
                    await ctx_or_interaction.send(message)
                    if processing_msg:
                        await processing_msg.delete()
                
        except Exception as e:
            logger.error(f"Error in recall command: {e}")
            message = "기억을 불러오는데 실패했습니다."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()

    @discord.app_commands.command(
        name="forget",
        description="정보를 잊어버립니다"
    )
    async def forget_slash(self, interaction: discord.Interaction, nickname: str):
        """Slash command version"""
        await self._handle_forget(interaction, nickname)

    @commands.command(name='잊어')
    async def forget_prefix(self, ctx: commands.Context, nickname: str):
        """Prefix command version"""
        await self._handle_forget(ctx, nickname)

    async def _handle_forget(self, ctx_or_interaction, nickname: str):
        processing_msg = None
        try:
            # Get user name
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)

            if self.memory_db.forget(nickname):
                message = f"'{nickname}'에 대한 모든 정보를 삭제했습니다."
            else:
                message = f"'{nickname}'에 대한 정보를 찾을 수 없습니다."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.channel.send(message)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()
                
        except Exception as e:
            logger.error(f"Error in forget command: {e}")
            message = "올바른 형식으로 입력해주세요"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error

    async def on_app_command_error(self, interaction: discord.Interaction, error: AppCommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"명령어 사용 제한 중입니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.",
                ephemeral=True
            )
        else:
            logger.error(f"Slash command error in {interaction.command}: {error}")
            error_messages = [
                "예상치 못한 오류가 발생했습니다.",
                "가능한 해결 방법:",
                "• 잠시 후 다시 시도",
                "• 명령어 사용법 확인 (`/help` 명령어 사용)",
                "• 봇 관리자에게 문의"
            ]
            await interaction.response.send_message("\n".join(error_messages), ephemeral=True) 