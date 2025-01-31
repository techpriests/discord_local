from discord.ext import commands
import discord

class SystemCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="핑", help="봇의 지연시간을 확인합니다", aliases=["ping", "레이턴시"])
    async def ping(self, ctx):
        try:
            embed = discord.Embed(title="🏓 퐁!", color=discord.Color.green())
            embed.add_field(name="지연시간", value=f"{round(self.bot.latency * 1000)}ms")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("오류가 발생했습니다.")
            print(f"Ping Error: {e}")
    
    @commands.command(name="따라해", help="메시지를 따라합니다", aliases=["copy", "mimic"])
    async def copy_message(self, ctx, *, message: str):
        try:
            await ctx.message.delete()
            await ctx.send(message)
        except discord.Forbidden:
            await ctx.send("메시지를 삭제할 권한이 없습니다.")
    
    @commands.command(aliases=["quit"])
    @commands.has_permissions(administrator=True)
    async def close(self, ctx):
        await self.bot.close()
        print("Bot Closed") 