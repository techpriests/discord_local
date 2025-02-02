import logging
import random
import re

import discord
from discord.ext import commands

from ..utils.decorators import command_handler
from .base_commands import BaseCommands

logger = logging.getLogger(__name__)


class EntertainmentCommands(BaseCommands):
    def __init__(self):
        """Initialize entertainment commands"""
        self.dice_pattern = re.compile(r"^(\d+)d(\d+)$")  # Pattern for "XdY"

    @commands.command(
        name="안녕",
        help="봇과 인사를 나눕니다",
        brief="인사하기",
        aliases=["인사", "하이"],
        description="봇과 인사를 나누는 명령어입니다.\n사용법: !!안녕",
    )
    async def hello(self, ctx):
        try:
            responses = ["안녕하세요", "안녕", "네, 안녕하세요"]
            await ctx.send(random.choice(responses))
        except discord.Forbidden as e:
            logger.error(f"Permission error in hello command: {e}")
            raise discord.Forbidden("메시지를 보낼 권한이 없습니다") from e
        except Exception as e:
            logger.error(f"Error in hello command: {e}")
            raise ValueError("인사하기에 실패했습니다") from e

    @commands.command(
        name="투표",
        help="여러 선택지 중 하나를 무작위로 선택합니다",
        brief="선택하기",
        aliases=["choice", "골라줘"],
        description="여러 선택지 중 하나를 무작위로 선택해주는 명령어입니다.\n"
        "사용법: !!투표 [선택지1] [선택지2] ...\n"
        "또는: !!골라줘 [선택지1] [선택지2] ...\n"
        "예시: !!투표 피자 치킨 햄버거",
    )
    async def choose(self, ctx, *args):
        """Choose one option from multiple choices

        Args:
            ctx: Command context
            args: List of choices to pick from

        Raises:
            ValueError: If less than 2 choices are provided
        """
        try:
            self._validate_choices(args)
            choice = self._make_random_choice(args)
            await self._send_choice_result(ctx, choice)

        except ValueError as e:
            raise e  # Re-raise user input errors
        except Exception as e:
            logger.error(f"Error in choose command: {e}")
            raise ValueError("선택에 실패했습니다") from e

    def _validate_choices(self, choices: tuple[str, ...]) -> None:
        """Validate choice options

        Args:
            choices: Tuple of choice options

        Raises:
            ValueError: If choices are invalid
        """
        if len(choices) < 2:
            raise ValueError(
                "최소 두 가지 이상의 선택지를 입력해주세요. " "(예시: !!투표 피자 치킨 햄버거)"
            )

        if any(len(choice) > 100 for choice in choices):
            raise ValueError("선택지는 100자를 넘을 수 없습니다")

        if len(choices) > 20:
            raise ValueError("선택지는 최대 20개까지 입력할 수 있습니다")

    def _make_random_choice(self, choices: tuple[str, ...]) -> str:
        """Make random choice from options

        Args:
            choices: Tuple of choice options

        Returns:
            str: Selected choice
        """
        return random.choice(choices)

    async def _send_choice_result(self, ctx: commands.Context, choice: str) -> None:
        """Send choice result

        Args:
            ctx: Command context
            choice: Selected choice
        """
        await ctx.send(f"음... 저는 '{choice}'을(를) 선택합니다!")

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
        "!!주사위 3d4  -> 4면체 주사위 3개",
    )
    async def roll_prefix(self, ctx, dice_str: str = "1d6"):
        """Roll dice using XdY format (e.g., 2d6 for two six-sided dice)"""
        await self._handle_roll(ctx, dice_str)

    @discord.app_commands.command(
        name="roll", description="주사위를 굴립니다 (예: 2d6은 6면체 주사위 2개)"
    )
    async def roll_slash(self, interaction: discord.Interaction, dice: str = "1d6"):
        """Slash command version of dice roll"""
        await self._handle_roll(interaction, dice)

    @command_handler()
    async def _handle_roll(self, ctx_or_interaction, dice_str: str = "1d6"):
        """Handle dice roll command

        Args:
            ctx_or_interaction: Command context or interaction
            dice_str: Dice specification in XdY format (default: "1d6")

        Raises:
            ValueError: If dice format is invalid or numbers are out of range
        """
        try:
            num_dice, sides = self._parse_dice_string(dice_str)
            self._validate_dice_params(num_dice, sides)

            rolls = self._roll_dice(num_dice, sides)
            await self._send_roll_result(ctx_or_interaction, dice_str, rolls)

        except ValueError as e:
            raise e
        except Exception as e:
            logger.error(f"Error in dice roll: {e}")
            raise ValueError("주사위 굴리기에 실패했습니다") from e

    def _parse_dice_string(self, dice_str: str) -> tuple[int, int]:
        """Parse dice string into number of dice and sides

        Args:
            dice_str: Dice specification in XdY format

        Returns:
            tuple[int, int]: Number of dice and sides

        Raises:
            ValueError: If format is invalid
        """
        match = self.dice_pattern.match(dice_str.lower())
        if not match:
            raise ValueError("올바른 주사위 형식이 아닙니다. " "예시: 2d6, 1d20, 3d4")

        return int(match.group(1)), int(match.group(2))

    def _validate_dice_params(self, num_dice: int, sides: int):
        """Validate dice parameters

        Args:
            num_dice: Number of dice
            sides: Number of sides per die

        Raises:
            ValueError: If parameters are out of range
        """
        if num_dice < 1 or num_dice > 100:
            raise ValueError("주사위 개수는 1-100개 사이여야 합니다")
        if sides < 2 or sides > 100:
            raise ValueError("주사위 면의 수는 2-100 사이여야 합니다")

    def _roll_dice(self, num_dice: int, sides: int) -> list[int]:
        """Roll the specified dice

        Args:
            num_dice: Number of dice to roll
            sides: Number of sides per die

        Returns:
            list[int]: List of roll results
        """
        return [random.randint(1, sides) for _ in range(num_dice)]

    async def _send_roll_result(self, ctx_or_interaction, dice_str: str, rolls: list[int]):
        """Send dice roll results

        Args:
            ctx_or_interaction: Command context or interaction
            dice_str: Original dice specification
            rolls: List of roll results
        """
        total = sum(rolls)

        if len(rolls) == 1:
            result = f"🎲 주사위 (d{rolls[0]}) 결과: **{total}**"
        else:
            rolls_str = " + ".join(str(r) for r in rolls)
            result = f"🎲 주사위 ({dice_str}) 결과:\n" f"개별: {rolls_str}\n" f"총합: **{total}**"

        await self.send_response(ctx_or_interaction, result)
