from discord.ext import commands
import discord

class SystemCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(
        name="핑",
        help="봇의 응답 시간을 확인합니다",
        brief="핑 체크",
        aliases=["ping"],
        description="봇의 현재 응답 시간(지연 시간)을 밀리초(ms) 단위로 보여줍니다.\n"
                    "사용법: !!핑"
    )
    async def ping(self, ctx):
        try:
            embed = discord.Embed(title="🏓 퐁!", color=discord.Color.green())
            embed.add_field(name="지연시간", value=f"{round(self.bot.latency * 1000)}ms")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("오류가 발생했습니다.")
            print(f"Ping Error: {e}")
    
    @commands.command(
        name="따라해",
        help="메시지를 따라합니다",
        brief="메시지 따라하기",
        aliases=["copy", "mimic"],
        description="입력한 메시지를 그대로 따라합니다.\n"
                    "사용법: !!따라해 [메시지]\n"
                    "예시: !!따라해 안녕하세요"
    )
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