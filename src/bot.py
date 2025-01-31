from discord.ext import commands
import discord
from typing import List
from src.services.memory_db import MemoryDB
import logging

logger = logging.getLogger(__name__)

class DiscordBot:
    def __init__(self, command_prefix: str = "!!"):
        self.bot = commands.Bot(command_prefix=command_prefix, intents=discord.Intents.all())
        self.api_service = None
        self.memory_db = MemoryDB()
        
        @self.bot.event
        async def on_ready():
            print(f"{self.bot.user.name} 로그인 성공")
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

    @commands.command(name='환율', aliases=['exchange'])
    async def exchange_rate(self, ctx: commands.Context, currency: str = None, amount: float = 1.0):
        """Get exchange rates for specific currencies
        Usage: 
            !!환율 - Shows all rates for 1000 KRW
            !!환율 엔화 - Converts 1 JPY to KRW
            !!환율 달러 100 - Converts 100 USD to KRW
            !!환율 원달러 - Converts 1 KRW to USD
            !!환율 원엔화 100 - Converts 100 KRW to JPY
        """ 

    @commands.command(name='기억')
    async def remember(self, ctx: commands.Context, *, content: str):
        """Remember information about a user
        Usage: !!기억 [text] [user nickname]
        Example: !!기억 좋아하는 게임 철수
        """
        try:
            # Split the last word as nickname
            *text_parts, nickname = content.rsplit(maxsplit=1)
            if not text_parts:
                await ctx.send("텍스트와 닉네임을 모두 입력해주세요.")
                return
                
            text = ' '.join(text_parts)
            author = str(ctx.author)  # Get Discord username of command user
            
            # Store in database
            if self.memory_db.remember(text, nickname, author):
                await ctx.send(f"기억했습니다: {text} → {nickname}")
            else:
                await ctx.send("기억하는데 실패했습니다.")
                
        except Exception as e:
            logger.error(f"Error in remember command: {e}")
            await ctx.send("올바른 형식으로 입력해주세요: !!기억 [텍스트] [닉네임]")

    @commands.command(name='알려')
    async def recall(self, ctx: commands.Context, *, nickname: str):
        """Recall information about a user
        Usage: !!알려 [nickname]
        Example: !!알려 철수
        """
        try:
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
                
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"'{nickname}'에 대한 기억이 없습니다.")
                
        except Exception as e:
            logger.error(f"Error in recall command: {e}")
            await ctx.send("기억을 불러오는데 실패했습니다.")

    @commands.command(name='잊어')
    async def forget(self, ctx: commands.Context, *, nickname: str):
        """Delete all information about a user
        Usage: !!잊어 [nickname]
        Example: !!잊어 철수
        """
        try:
            if self.memory_db.forget(nickname):
                await ctx.send(f"'{nickname}'에 대한 모든 정보를 삭제했습니다.")
            else:
                await ctx.send(f"'{nickname}'에 대한 정보를 찾을 수 없습니다.")
                
        except Exception as e:
            logger.error(f"Error in forget command: {e}")
            await ctx.send("올바른 형식으로 입력해주세요: !!잊어 [닉네임]") 