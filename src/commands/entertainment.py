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
from src.services.gacha.general import GeneralGachaCalculator

logger = logging.getLogger(__name__)


class EntertainmentCommands(BaseCommands):
    def __init__(self) -> None:
        """Initialize entertainment commands"""
        super().__init__()
        self.dice_pattern = re.compile(r"^(\d+)d(\d+)$")  # Pattern for "XdY"
        self.active_polls: Dict[int, Poll] = {}  # channel_id -> Poll
        self.gacha_calculator = GeneralGachaCalculator()

    @commands.command(
        name="안녕",
        help="봇과 인사를 나눕니다",
        brief="인사하기",
        aliases=["인사", "하이"],
        description="봇과 인사를 나누는 명령어입니다.\n사용법: 뮤 안녕",
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
        "사용법: 뮤 골라줘 [선택지1] [선택지2] ...\n"
        "또는: 뮤 투표 선택지1] [선택지2] ...\n"
        "예시: 뮤 투표 피자 치킨 햄버거",
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
                "최소 두 가지 이상의 선택지를 입력해줘. " "(예시: 뮤 투표 피자 치킨 햄버거)"
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
        "사용법: 뮤 주사위 [개수]d[면수]\n"
        "예시:\n"
        "뮤 주사위 2d6  -> 6면체 주사위 2개\n"
        "뮤 주사위 1d20 -> 20면체 주사위 1개\n"
        "뮤 주사위 3d4  -> 4면체 주사위 3개",
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

    @app_commands.command(
        name="gacha",
        description="일반 가챠 확률 계산"
    )
    @app_commands.describe(
        rate="확률 (퍼센트, 예: 0.75)",
        attempts="시도 횟수"
    )
    async def gacha_slash(
        self,
        interaction: discord.Interaction,
        rate: float,
        attempts: int
    ) -> None:
        """Slash command for simple gacha probability calculation"""
        await self._handle_gacha_calc(interaction, rate, attempts, None)

    @app_commands.command(
        name="gacha_resource",
        description="자원 기반 가챠 확률 계산"
    )
    @app_commands.describe(
        rate="확률 (퍼센트, 예: 0.75)",
        resource_name="자원 이름 (예: 돌, 젬, 크리스탈)",
        amount="보유 자원량",
        cost="뽑기당 비용"
    )
    async def gacha_resource_slash(
        self,
        interaction: discord.Interaction,
        rate: float,
        resource_name: str,
        amount: int,
        cost: int
    ) -> None:
        """Slash command for resource-based gacha probability calculation"""
        # Create resource info structure
        if amount <= 0 or cost <= 0:
            await interaction.response.send_message(
                "❌ 자원량과 비용은 양수여야 해.",
                ephemeral=True
            )
            return
        
        attempts = amount // cost
        if attempts == 0:
            await interaction.response.send_message(
                f"❌ 자원이 부족해. {cost} 이상 필요하지만 {amount}만 있어.",
                ephemeral=True
            )
            return
        
        remaining_resource = amount % cost
        resource_info = {
            'name': resource_name,
            'total': amount,
            'cost_per_pull': cost,
            'attempts': attempts,
            'remaining': remaining_resource
        }
        
        await self._handle_gacha_calc(interaction, rate, attempts, resource_info)

    async def _handle_gacha_calc(
        self,
        ctx_or_interaction: discord.Interaction | commands.Context,
        rate: float,
        attempts: int,
        resource_info: dict = None
    ) -> None:
        """Unified handler for gacha calculations (both prefix and slash commands)"""
        try:
            # Convert percentage to decimal
            rate_decimal = rate / 100.0
            
            # Calculate probabilities
            result = self.gacha_calculator.calculate_probability(rate_decimal, attempts)
            
            # Create embed
            user_name = self.get_user_name(ctx_or_interaction)
            embed = discord.Embed(
                title="🎲 일반 가챠 확률 계산",
                description=f"{user_name}의 {attempts}회 뽑기 결과야.",
                color=INFO_COLOR
            )

            # Add resource information if using resource calculation
            if resource_info:
                embed.add_field(
                    name="자원 정보",
                    value=f"보유 {resource_info['name']}: {resource_info['total']:,}\n"
                          f"뽑기당 비용: {resource_info['cost_per_pull']:,}\n"
                          f"가능한 뽑기: {resource_info['attempts']:,}회\n"
                          f"남는 {resource_info['name']}: {resource_info['remaining']:,}",
                    inline=False
                )
            
            embed.add_field(
                name="뽑기 정보",
                value=f"개별 성공률: {result['rate_percent']:.3f}%\n"
                      f"시도 횟수: {attempts:,}회",
                inline=False
            )

            success_percent = result['success_probability'] * 100
            failure_percent = result['failure_probability'] * 100
            expected = result['expected_successes']

            embed.add_field(
                name="결과",
                value=f"최소 1회 성공할 확률: **{success_percent:.2f}%**\n"
                      f"모두 실패할 확률: {failure_percent:.2f}%\n"
                      f"예상 성공 횟수: {expected:.2f}회",
                inline=False
            )

            # Add tips for different probability ranges
            if success_percent >= 95:
                tip = "🟢 매우 높은 확률이야! 거의 확실해."
            elif success_percent >= 80:
                tip = "🟡 높은 확률이야. 기대해도 좋을 것 같아."
            elif success_percent >= 50:
                tip = "🟠 반반 정도야. 운이 필요해."
            else:
                # Calculate additional pulls needed for 50% chance
                try:
                    total_for_50 = self.gacha_calculator.calculate_attempts_for_probability(rate_decimal, 0.5)
                    additional_needed = max(0, total_for_50 - attempts)
                    
                    if additional_needed == 0:
                        tip = "🟠 이미 50% 확률에 가까워!"
                    else:
                        tip = f"💡 50% 확률까지 {additional_needed:,}회 더 필요해 (총 {total_for_50:,}회)"
                except:
                    # Fallback to original messages if calculation fails
                    if success_percent >= 20:
                        tip = "🔴 낮은 확률이야. 운에 맡겨야겠어."
                    else:
                        tip = "⚫ 매우 낮은 확률이야. 기적이 필요해."

            embed.add_field(
                name="💡 팁",
                value=tip,
                inline=False
            )

            # Send response
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)

        except ValueError as e:
            error_msg = str(e)
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(
                    f"❌ {error_msg}",
                    ephemeral=True
                )
            else:
                await self.send_error(ctx_or_interaction, error_msg, ephemeral=True)

    @commands.command(
        name="가챠",
        help="일반 가챠 확률 계산",
        brief="가챠 확률 계산",
        aliases=["gacha", "뽑기확률"],
        description="일반 가챠 게임의 확률을 계산해주는 명령어야.\n"
                   "사용법 1: 뮤 가챠 [확률%] [시도횟수]\n"
                   "사용법 2: 뮤 가챠 [확률%] [자원명:보유량/비용]\n"
                   "예시: 뮤 가챠 0.75 30\n"
                   "     뮤 가챠 0.75 돌:12050/600\n"
                   "     뮤 가챠 1.5 젬:8400/300"
    )
    async def gacha_probability(
        self, 
        ctx: commands.Context, 
        rate: float, 
        *args
    ) -> None:
        """Calculate general gacha probabilities
        
        Args:
            ctx: Command context
            rate: Pull rate as percentage (e.g., 0.75 for 0.75%)
            *args: Either [attempts] or [resource:amount/cost]
        """
        try:
            # Parse arguments
            if len(args) == 1:
                arg = args[0]
                
                # Check if it's resource format or direct attempts
                if ':' in arg and '/' in arg:
                    # Resource format: 뮤 가챠 0.75 돌:12050/600
                    try:
                        # Split by colon first
                        if arg.count(':') != 1:
                            await self.send_error(
                                ctx,
                                "자원 형식: [자원명:보유량/비용] (예: 돌:12050/600)",
                                ephemeral=True
                            )
                            return
                        
                        resource_name, amount_cost_str = arg.split(':', 1)
                        
                        # Split by slash
                        if amount_cost_str.count('/') != 1:
                            await self.send_error(
                                ctx,
                                "자원 형식: [자원명:보유량/비용] (예: 돌:12050/600)",
                                ephemeral=True
                            )
                            return
                        
                        resource_amount_str, cost_per_pull_str = amount_cost_str.split('/', 1)
                        
                        resource_amount = int(resource_amount_str)
                        cost_per_pull = int(cost_per_pull_str)
                        
                        if resource_amount <= 0 or cost_per_pull <= 0:
                            raise ValueError("자원과 비용은 양수여야 해.")
                        
                        # Calculate possible attempts
                        attempts = resource_amount // cost_per_pull
                        remaining_resource = resource_amount % cost_per_pull
                        
                        if attempts == 0:
                            await self.send_error(
                                ctx,
                                f"자원이 부족해. {cost_per_pull} 이상 필요하지만 {resource_amount}만 있어.",
                                ephemeral=True
                            )
                            return
                        
                        resource_info = {
                            'name': resource_name,
                            'total': resource_amount,
                            'cost_per_pull': cost_per_pull,
                            'attempts': attempts,
                            'remaining': remaining_resource
                        }
                        
                    except ValueError as e:
                        await self.send_error(
                            ctx,
                            f"자원 형식이 잘못됨: {str(e)}\n올바른 형식: [자원명:보유량/비용] (예: 돌:12050/600)",
                            ephemeral=True
                        )
                        return
                else:
                    # Direct attempts format: 뮤 가챠 0.75 30
                    try:
                        attempts = int(arg)
                        resource_info = None
                    except ValueError:
                        await self.send_error(
                            ctx,
                            "시도 횟수는 숫자여야 해.",
                            ephemeral=True
                        )
                        return
            else:
                await self.send_error(
                    ctx,
                    "사용법: 뮤 가챠 [확률%] [시도횟수] 또는 뮤 가챠 [확률%] [자원명:보유량/비용]",
                    ephemeral=True
                )
                return
            
            # Use unified handler
            await self._handle_gacha_calc(ctx, rate, attempts, resource_info)

        except Exception as e:
            logger.error(f"Error in gacha command: {e}")
            await self.send_error(
                ctx,
                "가챠 확률 계산 중 오류가 발생했어.",
                ephemeral=True
            )

    @commands.command(
        name="가챠다중",
        help="다중 캐릭터 가챠 확률 계산",
        brief="다중 가챠 확률",
        aliases=["gacha_multi", "다중뽑기"],
        description="여러 캐릭터를 동시에 노리는 가챠 확률을 계산해주는 명령어야.\n"
                   "사용법: 뮤 가챠다중 [캐릭터1:확률1] [캐릭터2:확률2] [시도횟수]\n"
                   "예시: 뮤 가챠다중 A:0.75 B:1.0 30\n"
                   "     뮤 가챠다중 루시엘:0.5 미카엘:0.8 한세:1.2 100"
    )
    async def multi_gacha_probability(
        self, 
        ctx: commands.Context, 
        *args
    ) -> None:
        """Calculate multi-character gacha probabilities
        
        Args:
            ctx: Command context
            *args: Variable arguments containing character:rate pairs and attempts
        """
        try:
            if len(args) < 3:
                await self.send_error(
                    ctx,
                    "사용법: 뮤 가챠다중 [캐릭터1:확률1] [캐릭터2:확률2] [시도횟수]\n"
                    "예시: 뮤 가챠다중 A:0.75 B:1.0 30",
                    ephemeral=True
                )
                return

            # Parse attempts (last argument)
            try:
                attempts = int(args[-1])
            except ValueError:
                await self.send_error(
                    ctx,
                    "시도 횟수는 숫자여야 해.",
                    ephemeral=True
                )
                return

            # Parse character:rate pairs
            characters = []
            for arg in args[:-1]:  # All arguments except the last one (attempts)
                if ':' not in arg:
                    await self.send_error(
                        ctx,
                        f"잘못된 형식: {arg}\n"
                        "올바른 형식: 캐릭터이름:확률",
                        ephemeral=True
                    )
                    return
                
                try:
                    name, rate_str = arg.split(':', 1)
                    rate = float(rate_str) / 100.0  # Convert percentage to decimal
                    characters.append((name, rate))
                except ValueError:
                    await self.send_error(
                        ctx,
                        f"확률 값이 잘못됨: {rate_str}\n"
                        "확률은 숫자여야 해.",
                        ephemeral=True
                    )
                    return

            # Calculate probabilities
            result = self.gacha_calculator.calculate_multi_character_probability(
                characters, attempts
            )
            
            # Create embed
            user_name = self.get_user_name(ctx)
            embed = discord.Embed(
                title="🎲 다중 캐릭터 가챠 확률 계산",
                description=f"{user_name}의 {attempts}회 뽑기 결과야.",
                color=INFO_COLOR
            )

            # Character information
            char_info = []
            for char in result['characters']:
                char_info.append(
                    f"**{char['name']}**: {char['rate_percent']:.3f}% (개별 성공률: {char['probability']*100:.2f}%)"
                )
            
            embed.add_field(
                name="캐릭터 정보",
                value="\n".join(char_info),
                inline=False
            )

            # Scenarios
            scenarios_text = []
            total_scenarios = len(result['scenarios'])
            
            if len(characters) <= 3:
                # Show all scenarios for 2-3 characters (4-8 scenarios)
                for scenario_key, scenario in result['scenarios'].items():
                    prob_percent = scenario['probability'] * 100
                    scenarios_text.append(f"**{scenario['description']}**: {prob_percent:.2f}%")
                
                scenario_title = f"시나리오별 확률 (전체 {total_scenarios}개)"
            else:
                # Show top 10 scenarios for 4-5 characters to avoid overwhelming the display
                count = 0
                for scenario_key, scenario in result['scenarios'].items():
                    if count < 10:
                        prob_percent = scenario['probability'] * 100
                        scenarios_text.append(f"**{scenario['description']}**: {prob_percent:.2f}%")
                        count += 1
                    else:
                        break
                
                if total_scenarios > 10:
                    remaining = total_scenarios - 10
                    scenarios_text.append(f"*... 외 {remaining}개 시나리오 더 있음*")
                
                scenario_title = f"주요 시나리오 확률 (상위 10개, 전체 {total_scenarios}개)"

            embed.add_field(
                name=scenario_title,
                value="\n".join(scenarios_text),
                inline=False
            )

            # Add tip based on best scenario
            # Find the all-success scenario
            all_success_prob = 0.0
            for scenario in result['scenarios'].values():
                if len(scenario['characters']) == len(characters):
                    all_success_prob = scenario['probability'] * 100
                    break
            
            if len(characters) == 2:
                if all_success_prob >= 80:
                    tip = "🟢 두 캐릭터를 모두 얻을 확률이 높아!"
                elif all_success_prob >= 50:
                    tip = "🟡 둘 다 얻을 확률이 적당해."
                elif all_success_prob >= 20:
                    tip = "🟠 둘 다 얻기는 어려워 보여."
                else:
                    tip = "🔴 둘 다 얻기는 매우 어려워."
            else:
                if all_success_prob >= 50:
                    tip = "🟢 모든 캐릭터를 얻을 확률이 괜찮아!"
                elif all_success_prob >= 10:
                    tip = "🟡 모든 캐릭터를 얻기는 어려워."
                else:
                    tip = "🔴 모든 캐릭터를 얻기는 매우 어려워."

            embed.add_field(
                name="💡 팁",
                value=tip,
                inline=False
            )

            await ctx.send(embed=embed)

        except ValueError as e:
            await self.send_error(
                ctx,
                str(e),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in multi gacha command: {e}")
            await self.send_error(
                ctx,
                "다중 가챠 확률 계산 중 오류가 발생했어.",
                ephemeral=True
            )
