from discord.ext import commands
import discord
from typing import List

class DiscordBot:
    def __init__(self, command_prefix: str = "!!"):
        self.bot = commands.Bot(command_prefix=command_prefix, intents=discord.Intents.all())
        
        @self.bot.event
        async def on_ready():
            print(f"{self.bot.user.name} 로그인 성공")
            await self.bot.change_presence(status=discord.Status.online, activity=discord.Game('LIVE'))
    
    def load_cogs(self, cogs: List[commands.Cog]):
        for cog in cogs:
            self.bot.add_cog(cog)
    
    def run(self, token: str):
        self.bot.run(token) 