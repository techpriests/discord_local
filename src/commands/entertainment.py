from discord.ext import commands
import discord
import random
import re
from .base_commands import BaseCommands
from ..utils.decorators import command_handler

class EntertainmentCommands(BaseCommands):
    def __init__(self):
        self.dice_pattern = re.compile(r'^(\d+)d(\d+)$')  # Pattern for "XdY"
    
    @commands.command(
        name="안녕",
        help="봇과 인사를 나눕니다",
        brief="인사하기",
        aliases=["인사", "하이"],
        description="봇과 인사를 나누는 명령어입니다.\n사용법: !!안녕"
    )
    async def hello(self, ctx):
        responses = ["안녕하세요", "안녕", "네, 안녕하세요"]
        await ctx.send(random.choice(responses))
    
    @commands.command(
        name="투표",
        help="여러 선택지 중 하나를 무작위로 선택합니다",
        brief="선택하기",
        aliases=["choice", "골라줘"],
        description="여러 선택지 중 하나를 무작위로 선택해주는 명령어입니다.\n"
                    "사용법: !!투표 [선택지1] [선택지2] ...\n"
                    "또는: !!골라줘 [선택지1] [선택지2] ...\n"
                    "예시: !!투표 피자 치킨 햄버거"
    )
    async def choose(self, ctx, *args):
        if len(args) < 2:
            await ctx.send("최소 두 가지 이상의 선택지를 입력해주세요. (예시: !!투표 피자 치킨 햄버거)")
            return
        await ctx.send(f"음... 저는 '{random.choice(args)}'을(를) 선택합니다!")
    
    @commands.command(
        name="주사위",
        help="주사위를 굴립니다 (XdY 형식 사용)",
        brief="주사위 굴리기",
        aliases=["roll", "굴려"],
        description="지정한 개수와 면의 수만큼 주사위를 굴립니다.\n"
                    "사용법: !!주사위 [개수]d[면수]\n"
                    "예시:\n"
                    "!!주사위 2d6  -> 6면체 주사위 2개\n"
                    "!!주사위 1d20 -> 20면체 주사위 1개\n"
                    "!!주사위 3d4  -> 4면체 주사위 3개"
    )
    async def roll_prefix(self, ctx, dice_str: str = "1d6"):
        """Roll dice using XdY format (e.g., 2d6 for two six-sided dice)"""
        await self._handle_roll(ctx, dice_str)

    @discord.app_commands.command(
        name="roll",
        description="주사위를 굴립니다 (예: 2d6은 6면체 주사위 2개)"
    )
    async def roll_slash(self, interaction: discord.Interaction, dice: str = "1d6"):
        """Slash command version of dice roll"""
        await self._handle_roll(interaction, dice)

    @command_handler()
    async def _handle_roll(self, ctx_or_interaction, dice_str: str = "1d6"):
        # Parse dice string
        match = self.dice_pattern.match(dice_str.lower())
        if not match:
            raise ValueError("올바른 주사위 형식이 아닙니다. 예시: 2d6, 1d20, 3d4")
        
        num_dice = int(match.group(1))
        sides = int(match.group(2))
        
        # Validate input
        if num_dice < 1 or num_dice > 100:
            raise ValueError("주사위 개수는 1-100개 사이여야 합니다")
        if sides < 2 or sides > 100:
            raise ValueError("주사위 면의 수는 2-100 사이여야 합니다")
        
        # Roll dice
        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls)
        
        # Create response
        if num_dice == 1:
            result = f"🎲 주사위 (d{sides}) 결과: **{total}**"
        else:
            rolls_str = ' + '.join(str(r) for r in rolls)
            result = f"🎲 주사위 ({dice_str}) 결과:\n개별: {rolls_str}\n총합: **{total}**"
        
        return await self.send_response(ctx_or_interaction, result) 