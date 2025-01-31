from discord.ext import commands
import discord
import random

class EntertainmentCommands(commands.Cog):
    @commands.command(name="안녕", help="인사말", aliases=["인사", "하이"])
    async def hello(self, ctx):
        responses = ["안녕하세요", "안녕", "네, 안녕하세요"]
        await ctx.send(random.choice(responses))
    
    @commands.command(name="투표", help="여러 선택지 중 하나를 골라드립니다", aliases=["choice", "골라줘"])
    async def choose(self, ctx, *args):
        if len(args) < 2:
            await ctx.send("최소 두 가지 이상의 선택지를 입력해주세요. (예시: !!투표 피자 치킨 햄버거)")
            return
        await ctx.send(f"음... 저는 '{random.choice(args)}'을(를) 선택합니다!")
    
    @commands.command(name="주사위", help="주사위를 굴립니다", aliases=["roll", "굴려"])
    async def roll_dice(self, ctx, sides: int = 6, times: int = 1):
        try:
            if not 2 <= sides <= 100 or not 1 <= times <= 10:
                await ctx.send("주사위는 2~100면, 1~10회까지 가능합니다!")
                return
            
            results = [random.randint(1, sides) for _ in range(times)]
            
            embed = discord.Embed(title="🎲 주사위 결과", color=discord.Color.blue())
            embed.add_field(
                name=f"D{sides} {times}회 결과", 
                value=", ".join(map(str, results)), 
                inline=False
            )
            
            if times > 1:
                embed.add_field(name="합계", value=str(sum(results)), inline=False)
            
            await ctx.send(embed=embed)
        except ValueError:
            await ctx.send("올바른 숫자를 입력해주세요!") 