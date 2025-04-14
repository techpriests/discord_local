import logging
import random
import re
from typing import List, Optional, Dict, Any, Tuple, cast
import asyncio

import discord
from discord.ext import commands
from discord import app_commands

from src.utils.decorators import command_handler
from .base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.entertainment_types import Poll, PollOption
from src.utils.constants import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR

logger = logging.getLogger(__name__)


class EntertainmentCommands(BaseCommands):
    def __init__(self) -> None:
        """Initialize entertainment commands"""
        super().__init__()
        self.dice_pattern = re.compile(r"^(\d+)d(\d+)$")  # Pattern for "XdY"
        self.active_polls: Dict[int, Poll] = {}  # channel_id -> Poll

    @commands.command(
        name="안녕",
        help="봇과 인사를 나눕니다",
        brief="인사하기",
        aliases=["인사", "하이"],
        description="봇과 인사를 나누는 명령어입니다.\n사용법: !!안녕",
    )
    async def hello(self, ctx: commands.Context) -> None:
        """Greet the user"""
        try:
            responses = ["안녕~", "안녕!", "반가워."]
            await ctx.send(random.choice(responses))
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["send_messages"])
        except Exception as e:
            logger.error(f"Error in hello command: {e}")
            raise ValueError("인사하기에 실패했어") from e

    @commands.command(
        name="투표",
        help="여러 선택지 중 하나를 무작위로 선택해",
        brief="선택하기",
        aliases=["choice", "골라줘"],
        description="여러 선택지 중 하나를 무작위로 선택해주는 명령어야.\n"
        "사용법: !!투표 [선택지1] [선택지2] ...\n"
        "또는: !!골라줘 [선택지1] [선택지2] ...\n"
        "예시: !!투표 피자 치킨 햄버거",
    )
    async def choose(self, ctx: commands.Context, *args: str) -> None:
        """Choose one option from multiple choices"""
        try:
            self._validate_choices(args)
            
            # 25% chance of refusing to choose
            if random.random() < 0.25:
                await ctx.send("그 정도는 스스로 골라줘.")
                return
                
            choice = self._make_random_choice(args)
            await ctx.send(f"나는 '{choice}'를 고를래.")
        except discord.Forbidden:
            raise commands.BotMissingPermissions(["send_messages"])
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error(f"Error in choose command: {e}")
            raise ValueError("뭔가 잘못된 것 같아.") from e

    def _validate_choices(self, choices: tuple[str, ...]) -> None:
        """Validate choice options

        Args:
            choices: Tuple of choice options

        Raises:
            ValueError: If choices are invalid
        """
        if len(choices) < 2:
            raise ValueError(
                "최소 두 가지 이상의 선택지를 입력해줘. " "(예시: !!투표 피자 치킨 햄버거)"
            )

        if any(len(choice) > 100 for choice in choices):
            raise ValueError("선택지는 100자를 넘을 수 없어")

        if len(choices) > 20:
            raise ValueError("선택지는 최대 20개까지 입력할 수 있어")

    def _make_random_choice(self, choices: tuple[str, ...]) -> str:
        """Make random choice from options

        Args:
            choices: Tuple of choice options

        Returns:
            str: Selected choice
        """
        return random.choice(choices)

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
    async def roll_dice(
        self,
        ctx: commands.Context,
        dice_str: str
    ) -> None:
        """Roll dice command"""
        try:
            num_dice, sides = self._parse_dice_str(dice_str)
            self._validate_dice_params(num_dice, sides)
            
            results = [random.randint(1, sides) for _ in range(num_dice)]
            total = sum(results)
            
            await self._send_dice_results(ctx, results, total)
            
        except ValueError as e:
            await self.send_error(ctx, str(e))
        except Exception as e:
            logger.error(f"Error in roll_dice: {e}")
            await self.send_error(ctx, "명령어 실행에 실패했어")

    def _parse_dice_str(self, dice_str: str) -> Tuple[int, int]:
        """Parse dice string into number and sides
        
        Args:
            dice_str: Dice string in format XdY

        Returns:
            Tuple[int, int]: Number of dice and sides per die

        Raises:
            ValueError: If format is invalid
        """
        match = self.dice_pattern.match(dice_str)
        if not match:
            raise ValueError("올바른 주사위 형식이 아니야. 예시: 2d6, 1d20")
        
        return int(match.group(1)), int(match.group(2))

    def _validate_dice_params(self, num_dice: int, sides: int) -> None:
        """Validate dice parameters
        
        Args:
            num_dice: Number of dice
            sides: Number of sides per die

        Raises:
            ValueError: If parameters are invalid
        """
        if not 1 <= num_dice <= 100:
            raise ValueError("주사위 개수는 1-100개 사이여야 해")
        if not 2 <= sides <= 100:
            raise ValueError("주사위 면의 수는 2-100 사이여야 해")

    async def _send_dice_results(self, ctx: commands.Context, results: list[int], total: int) -> None:
        """Send dice roll results

        Args:
            ctx: Command context
            results: List of roll results
            total: Sum of roll results
        """
        if len(results) == 1:
            result = f"🎲 주사위 (d{results[0]}) 결과: **{total}**"
        else:
            rolls_str = " + ".join(str(r) for r in results)
            result = f"🎲 주사위 ({rolls_str}) 결과:\n" f"총합: **{total}**"

        await ctx.send(result)

    @app_commands.command(name="dice", description="주사위를 굴립니다")
    async def dice_slash(
        self, 
        interaction: discord.Interaction, 
        sides: Optional[int] = None
    ) -> None:
        """Slash command for dice roll"""
        await self._handle_dice(interaction, sides)

    @command_handler()
    async def _handle_dice(
        self, 
        ctx_or_interaction: CommandContext, 
        sides: Optional[int] = None
    ) -> None:
        """Handle dice roll request"""
        if not sides:
            sides = 6
        elif sides < 2:
            return await self.send_response(
                ctx_or_interaction,
                "주사위는 최소 2면이어야 해"
            )
        elif sides > 100:
            return await self.send_response(
                ctx_or_interaction,
                "주사위는 최대 100면까지만 가능해"
            )

        result = random.randint(1, sides)
        await self._send_dice_result(ctx_or_interaction, result, sides)

    async def _send_dice_result(
        self, 
        ctx_or_interaction: CommandContext, 
        result: int, 
        sides: int
    ) -> None:
        """Send dice roll result"""
        embed = discord.Embed(
            title="🎲 주사위 결과",
            description=f"{sides}면 주사위를 굴려서...\n**{result}**이(가) 나왔어.",
            color=INFO_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed)

    @app_commands.command(name="poll", description="투표를 생성합니다")
    async def poll_slash(
        self, 
        interaction: discord.Interaction,
        title: str,
        options: str,
        max_votes: Optional[int] = None
    ) -> None:
        """Slash command for creating a poll"""
        await self._handle_poll_create(interaction, title, options, max_votes)

    @command_handler()
    async def _handle_poll_create(
        self,
        ctx_or_interaction: CommandContext,
        title: str,
        options_str: str,
        max_votes: Optional[int] = None
    ) -> None:
        """Handle poll creation request"""
        channel_id = self._get_channel_id(ctx_or_interaction)
        
        if channel_id in self.active_polls:
            return await self.send_response(
                ctx_or_interaction,
                "이 채널에 이미 진행 중인 투표가 있어"
            )

        options = self._parse_poll_options(options_str)
        if not self._validate_poll_options(options):
            return await self.send_response(
                ctx_or_interaction,
                "투표 옵션은 2개 이상 10개 이하여야 해"
            )

        poll = self._create_poll(title, options, max_votes)
        self.active_polls[channel_id] = poll
        
        await self._send_poll_embed(ctx_or_interaction, poll)

    def _get_channel_id(self, ctx_or_interaction: CommandContext) -> int:
        """Get channel ID from context or interaction"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.channel_id
        return cast(int, ctx_or_interaction.channel.id)  # Cast to ensure int

    def _parse_poll_options(self, options_str: str) -> List[str]:
        """Parse poll options from string"""
        return [opt.strip() for opt in options_str.split(',') if opt.strip()]

    def _validate_poll_options(self, options: List[str]) -> bool:
        """Validate poll options"""
        return 2 <= len(options) <= 10

    def _create_poll(
        self, 
        title: str, 
        options: List[str],
        max_votes: Optional[int] = None
    ) -> Poll:
        """Create new poll"""
        return Poll(
            title=title,
            options=[PollOption(name=opt, votes=0) for opt in options],
            voters=[],
            is_active=True,
            max_votes=max_votes
        )

    async def _send_poll_embed(
        self, 
        ctx_or_interaction: CommandContext, 
        poll: Poll
    ) -> None:
        """Send poll embed with current results"""
        embed = discord.Embed(
            title=f"📊 {poll['title']}", 
            color=INFO_COLOR
        )
        
        total_votes = sum(opt['votes'] for opt in poll['options'])
        
        for i, option in enumerate(poll['options']):
            percentage = (option['votes'] / total_votes * 100) if total_votes > 0 else 0
            bar = self._create_progress_bar(percentage)
            embed.add_field(
                name=f"{i+1}. {option['name']}",
                value=f"{bar} ({option['votes']} votes, {percentage:.1f}%)",
                inline=False
            )

        footer_text = "투표하려면 번호를 입력해줘"
        if poll['max_votes']:
            footer_text += f" (최대 {poll['max_votes']}표)"
        embed.set_footer(text=footer_text)

        await self.send_response(ctx_or_interaction, embed=embed)

    def _create_progress_bar(self, percentage: float, length: int = 20) -> str:
        """Create a text-based progress bar
        
        Args:
            percentage: Percentage to display (0-100)
            length: Length of the progress bar

        Returns:
            str: Progress bar string
        """
        filled = int(length * percentage / 100)
        return "█" * filled + "░" * (length - filled)

    @app_commands.command(name="vote", description="투표에 참여합니다")
    async def vote_slash(
        self, 
        interaction: discord.Interaction, 
        option: int
    ) -> None:
        """Slash command for voting in a poll"""
        await self._handle_vote(interaction, option)

    @command_handler()
    async def _handle_vote(
        self, 
        ctx_or_interaction: CommandContext, 
        option: int
    ) -> None:
        """Handle vote in poll"""
        channel_id = self._get_channel_id(ctx_or_interaction)
        user_id = self._get_user_id(ctx_or_interaction)
        
        if not self._validate_vote(channel_id, option, user_id):
            return
            
        poll = self.active_polls[channel_id]
        self._record_vote(poll, option - 1, user_id)
        
        await self._send_poll_embed(ctx_or_interaction, poll)

    def _get_user_id(self, ctx_or_interaction: CommandContext) -> int:
        """Get user ID from context or interaction"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.user.id
        return ctx_or_interaction.author.id

    def _validate_vote(self, channel_id: int, option: int, user_id: int) -> bool:
        """Validate vote attempt
        
        Args:
            channel_id: Channel ID where vote is cast
            option: Selected option number
            user_id: ID of user voting

        Returns:
            bool: True if vote is valid
        """
        if channel_id not in self.active_polls:
            return False

        poll = self.active_polls[channel_id]
        
        if not poll['is_active']:
            return False
            
        if option < 1 or option > len(poll['options']):
            return False
            
        if poll['max_votes'] and user_id in poll['voters']:
            if poll['voters'].count(user_id) >= poll['max_votes']:
                return False
                
        return True

    def _record_vote(self, poll: Poll, option_index: int, user_id: int) -> None:
        """Record a vote in the poll
        
        Args:
            poll: Poll to update
            option_index: Index of chosen option
            user_id: ID of user voting
        """
        poll['options'][option_index]['votes'] += 1
        poll['voters'].append(user_id)

    @app_commands.command(name="end_poll", description="투표를 종료합니다")
    async def end_poll_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for ending a poll"""
        await self._handle_end_poll(interaction)

    @command_handler()
    async def _handle_end_poll(self, ctx_or_interaction: CommandContext) -> None:
        """Handle poll ending request"""
        channel_id = self._get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_polls:
            return await self.send_response(
                ctx_or_interaction,
                "이 채널에 진행 중인 투표가 없어"
            )
            
        poll = self.active_polls[channel_id]
        poll['is_active'] = False
        
        await self._send_poll_results(ctx_or_interaction, poll)
        del self.active_polls[channel_id]

    async def _send_poll_results(
        self, 
        ctx_or_interaction: CommandContext, 
        poll: Poll
    ) -> None:
        """Send final poll results"""
        embed = discord.Embed(
            title=f"📊 투표 결과: {poll['title']}", 
            color=SUCCESS_COLOR
        )
        
        winner = max(poll['options'], key=lambda x: x['votes'])
        total_votes = sum(opt['votes'] for opt in poll['options'])
        
        for option in poll['options']:
            percentage = (option['votes'] / total_votes * 100) if total_votes > 0 else 0
            bar = self._create_progress_bar(percentage)
            is_winner = option['votes'] == winner['votes']
            name = f"👑 {option['name']}" if is_winner else option['name']
            embed.add_field(
                name=name,
                value=f"{bar} ({option['votes']} votes, {percentage:.1f}%)",
                inline=False
            )

        embed.set_footer(text=f"총 {total_votes}표가 집계되었습니다")
        await self.send_response(ctx_or_interaction, embed=embed)

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
            raise ValueError("주사위 굴리기에 실패했어") from e

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
            raise ValueError("올바른 주사위 형식이 아니야. " "예시: 2d6, 1d20, 3d4")

        return int(match.group(1)), int(match.group(2))

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
