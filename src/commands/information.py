import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Union, cast, Tuple
import io

import discord
import pytz
from discord.ext import commands
from discord.ext.commands import Context
from discord import File, app_commands

from src.services.api import APIService
from src.utils.decorators import command_handler
from src.utils.constants import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR
from src.commands.base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.api_types import GameInfo, CountryInfo
from src.utils.command_types import APIServiceProtocol

logger = logging.getLogger(__name__)

class InformationCommands(BaseCommands):
    """Commands for retrieving various information"""

    def __init__(self, api_service: APIServiceProtocol) -> None:
        """Initialize information commands

        Args:
            api_service: API service instance for external data
        """
        super().__init__()
        self.api = api_service

    def _check_api_state(self, api_name: str) -> None:
        """Check if API is initialized
        
        Args:
            api_name: Name of API to check
            
        Raises:
            ValueError: If API is not initialized
        """
        if not self.api.initialized:
            raise ValueError("API 서비스가 초기화되지 않았어")
            
        api_states = self.api.api_states
        if not api_states.get(api_name.lower(), False):
            raise ValueError(f"{api_name} API가 초기화되지 않았어")

    @discord.app_commands.command(name="population", description="국가의 인구수를 알려줄게")
    async def population_slash(self, interaction: discord.Interaction, country_name: str) -> None:
        """Slash command version"""
        await self._handle_population(interaction, country_name)

    @commands.command(
        name="인구",
        help="국가의 인구수를 알려줘",
        brief="인구 확인",
        aliases=["population"],
        description=(
            "국가의 인구, 수도, 지역 정보를 보여줘.\n"
            "사용법:\n"
            "• 뮤 인구 [국가명]\n"
            "• pt population [국가명]\n"
            "예시:\n"
            "• 뮤 인구 South Korea - 대한민국 정보\n"
            "• pt population Japan - 일본 정보\n"
            "• pt population United States - 미국 정보\n"
            "※ 영어로 국가명을 입력하면 더 정확한 결과를 얻을 수 있어."
        ),
    )
    async def population_prefix(self, ctx: commands.Context, *, country_name: str = None):
        """Prefix command version"""
        await self._handle_population(ctx, country_name)

    @command_handler()
    async def _handle_population(
        self, 
        ctx_or_interaction: CommandContext, 
        country_name: Optional[str] = None
    ) -> None:
        """Handle population information request"""
        try:
            self._check_api_state('population')
            
            if not self._validate_country_name(country_name):
                return await self.send_response(
                    ctx_or_interaction, 
                    "국가 이름을 2글자 이상 입력해줘",
                    ephemeral=True
                )

            processing_msg = None
            try:
                processing_msg = await self.send_response(
                    ctx_or_interaction, 
                    "국가 정보를 검색중이야...",
                    ephemeral=True
                )
                country = await self._get_country_info(country_name)
                await self._send_country_embed(ctx_or_interaction, country, processing_msg)
            except Exception as e:
                await self._handle_population_error(ctx_or_interaction, country_name, str(e))
            finally:
                if processing_msg:
                    try:
                        await processing_msg.delete()
                    except Exception as e:
                        logger.error(f"Error deleting processing message: {e}")
        except Exception as e:
            await self._handle_population_error(ctx_or_interaction, country_name, str(e))

    def _validate_country_name(self, country_name: Optional[str]) -> bool:
        """Validate country name input"""
        return bool(country_name and len(country_name.strip()) >= 2)

    async def _get_country_info(self, country_name: str) -> CountryInfo:
        """Get country information from API"""
        country_name = country_name.strip()[:50]
        country_name = "".join(c for c in country_name if c.isalnum() or c.isspace())
        return await self.api.population.get_country_info(country_name)

    async def _send_country_embed(
        self, 
        ctx_or_interaction: CommandContext, 
        country: CountryInfo, 
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send embed with country information

        Args:
            ctx_or_interaction: Command context or interaction
            country: Country information dictionary
            processing_msg: Optional processing message to delete (handled by caller)
        """
        # Check if 'name' key exists in the country dictionary
        country_name = country.get('name', {}).get('official', '정보없음')

        embed = discord.Embed(
            title=f"🌏 {country_name}", 
            color=discord.Color.green()
        )
        
        # Safely access population with a default value
        population = country.get('population', 0)
        embed.add_field(name="인구", value=f"{population:,}명", inline=False)
        embed.add_field(name="수도", value=country.get("capital", ["정보없음"])[0], inline=True)
        embed.add_field(name="지역", value=country.get("region", "정보없음"), inline=True)

        flags = country.get("flags", {})
        if "png" in flags:
            embed.set_thumbnail(url=flags["png"])

        await self._send_response(ctx_or_interaction, embed=embed)

    async def _handle_population_error(
        self, 
        ctx_or_interaction: CommandContext, 
        country_name: str, 
        error_msg: str
    ) -> None:
        """Handle errors in population command"""
        logger.error(f"Error getting population for {country_name}: {error_msg}")
        user_name = self.get_user_name(ctx_or_interaction)
        await self.send_response(
            ctx_or_interaction,
            f"{user_name}, 인구 정보를 가져오는데 실패했어: {country_name}",
            ephemeral=True
        )

    @discord.app_commands.command(name="game", description="Steam 게임의 동시접속자 수를 알려줄게")
    async def game_slash(self, interaction: discord.Interaction, game_name: str) -> None:
        """Slash command for game search"""
        await self._handle_steam(interaction, game_name)

    @commands.command(
        name="스팀",
        help="스팀 게임의 현재 플레이어 수를 알려줄거야",
        brief="스팀 게임 정보",
        aliases=["steam", "game"],
        description=(
            "스팀 게임의 현재 플레이어 수와 정보를 보여줘.\n"
            "사용법:\n"
            "• 뮤 스팀 [게임명]\n"
            "• pt steam [게임명]\n"
            "예시:\n"
            "• 뮤 스팀 Lost Ark\n"
            "• pt steam PUBG\n"
            "• pt steam Dota 2\n"
            "※ 정확한 게임명을 입력하면 더 좋은 결과를 얻을 수 있어."
        ),
    )
    async def steam_prefix(self, ctx: commands.Context, *, game_name: str = None):
        """Prefix command version"""
        await self._handle_steam(ctx, game_name)

    @command_handler()
    async def _handle_steam(self, ctx_or_interaction, game_name: Optional[str] = None) -> None:
        """Handle Steam game information request

        Args:
            ctx_or_interaction: Command context or interaction
            game_name: Name of the game to search for

        Raises:
            ValueError: If game not found or API error
        """
        try:
            self._check_api_state('steam')
            
            if not game_name:
                await self.send_response(
                    ctx_or_interaction,
                    "어라, 게임 이름도 없이 어떻게 찾아줄 수 있겠어?",
                    ephemeral=True
                )
                return

            processing_msg = None
            user_name = self.get_user_name(ctx_or_interaction)
            try:
                # Show processing message
                processing_msg = await self.send_response(
                    ctx_or_interaction,
                    f"{user_name}, 데이터베이스를 뒤져보는 중이야...",
                    ephemeral=True
                )

                game, similarity, similar_games = await self.api.steam.find_game(game_name)

                if not game:
                    if processing_msg:
                        try:
                            await processing_msg.delete()
                        except Exception as e:
                            logger.error(f"Error deleting processing message: {e}")
                    await self._send_game_not_found_embed(ctx_or_interaction, user_name)
                    return

                embed = await self._create_game_embed(game, similar_games, user_name)
                
                # Delete processing message before sending response
                if processing_msg:
                    try:
                        await processing_msg.delete()
                    except Exception as e:
                        logger.error(f"Error deleting processing message: {e}")
                
                await self.send_response(ctx_or_interaction, embed=embed)

            except Exception as e:
                logger.error(f"Error in steam command: {e}")
                if processing_msg:
                    try:
                        await processing_msg.delete()
                    except Exception as e:
                        logger.error(f"Error deleting processing message: {e}")
                await self._send_steam_error_embed(ctx_or_interaction, user_name)
        except Exception as e:
            await self._handle_steam_error(ctx_or_interaction, game_name, str(e))

    async def _send_game_not_found_embed(self, ctx_or_interaction, user_name: str):
        """Send embed for game not found error

        Args:
            ctx_or_interaction: Command context or interaction
            user_name: Name of the user who issued the command
        """
        embed = discord.Embed(
            title="❌ 모르겠어!", 
            description=f"{user_name}, 그 이름으로는 찾을 수 없었어.",
            color=ERROR_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed, ephemeral=True)

    async def _create_game_embed(
        self, game: dict, similar_games: Optional[List[dict]] = None, user_name: Optional[str] = None
    ) -> discord.Embed:
        """Create embed for game information

        Args:
            game: Game information dictionary
            similar_games: Optional list of similar games (not used)
            user_name: Name of the user who issued the command

        Returns:
            discord.Embed: Formatted embed with game information
        """
        # Ensure we have a user name, even if it's generic
        user_name = user_name or "사용자"
        
        embed = discord.Embed(
            title=f"🎮 {game['name']}", 
            description=f"{user_name}가 찾던 게임의 정보야.",
            color=SUCCESS_COLOR
        )

        if game.get("player_count") is not None:
            embed.add_field(name="현재 플레이어", value=f"{game['player_count']:,}명", inline=True)

        # Add game image if available
        if game.get("image_url"):
            embed.set_thumbnail(url=game["image_url"])

        # Add Steam store link if app_id is available
        if game.get("app_id"):
            store_url = f"https://store.steampowered.com/app/{game['app_id']}"
            embed.add_field(name="🛒 스팀 스토어", value=f"[게임 페이지 보러가기]({store_url})", inline=False)

        return embed

    async def _send_steam_error_embed(self, ctx_or_interaction, user_name: str):
        """Send embed for Steam API error

        Args:
            ctx_or_interaction: Command context or interaction
            user_name: Name of the user who issued the command
        """
        embed = discord.Embed(
            title="❌ 오류", 
            description=f"{user_name}, 뭔가 DB에 문제가 생긴 것 같아.", 
            color=ERROR_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Handle command errors

        Args:
            ctx: Command context
            error: The error that occurred
        """
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore command not found errors

        if isinstance(error, commands.CommandOnCooldown):
            await self._handle_cooldown_error(ctx, error)
        elif isinstance(error, commands.MissingRequiredArgument):
            await self._handle_missing_argument_error(ctx)
        else:
            await self._handle_unexpected_error(ctx, error)

    async def _handle_cooldown_error(self, ctx, error):
        """Handle command cooldown errors

        Args:
            ctx: Command context
            error: Cooldown error
        """
        user_name = self.get_user_name(ctx)
        await self.send_response(
            ctx,
            f"{user_name}, 명령어 사용 제한 중이야 {error.retry_after:.1f}초 후에 다시 시도해줘.",
            ephemeral=True
        )

    async def _handle_missing_argument_error(self, ctx):
        """Handle missing argument errors

        Args:
            ctx: Command context
        """
        user_name = self.get_user_name(ctx)
        await self.send_response(
            ctx,
            f"{user_name}, 필수 입력값이 누락되었어. `뮤 muhelp {ctx.command}` 로 사용법을 확인해줄래?",
            ephemeral=True
        )

    async def _handle_unexpected_error(self, ctx, error):
        """Handle unexpected errors

        Args:
            ctx: Command context
            error: The unexpected error
        """
        logger.error(f"Unexpected error in {ctx.command}: {error}")
        user_name = self.get_user_name(ctx)
        error_messages = [
            f"{user_name}, 예상치 못한 오류가 발생했어.",
            "가능한 해결 방법은:",
            "• 잠시 후 다시 시도하기",
            "• 명령어 사용법 확인 (`뮤 muhelp` 명령어 사용)",
            "• 관리자에게 문의",
        ]
        await self.send_response(
            ctx,
            "\n".join(error_messages),
            ephemeral=True
        )

    @commands.command(
        name="시간",
        help="세계 시간을 변환해줘",
        brief="시간 변환",
        aliases=["time"],
        description="한국 시간과 세계 각국의 시간을 비교해서 알려줄거야.\n"
        "사용법:\n"
        "• 뮤 시간 [지역] [시간]  -> 특정 지역/시간 변환\n"
        "• pt time [지역] [시간]  -> 특정 지역/시간 변환\n"
        "예시:\n"
        "• 뮤 시간  -> 주요 도시 시간 표시\n"
        "• 뮤 시간 US/Pacific  -> 특정 지역 시간 변환\n"
        "• pt time US/Pacific 09:00  -> 특정 시간 변환",
    )
    async def time_prefix(self, ctx, timezone: str = None, time_str: str = None):
        """Convert time between timezones
        Examples:
        뮤 시간  # Show all timezones
        뮤 시간 US/Pacific  # Convert current KR time to PST
        뮤 시간 US/Pacific 09:00  # Convert PST 09:00 to KR time
        """
        await self._handle_time(ctx, timezone, time_str)

    @discord.app_commands.command(name="time", description="세계 시간을 보여줘")
    async def time_slash(
        self, 
        interaction: discord.Interaction, 
        timezone: Optional[str] = None,
        time_str: Optional[str] = None
    ) -> None:
        """Slash command for world time"""
        await self._handle_time(interaction, timezone, time_str)

    async def _handle_time(
        self, 
        ctx_or_interaction: CommandContext, 
        timezone: Optional[str] = None,
        time_str: Optional[str] = None
    ) -> None:
        """Handle time conversion request"""
        try:
            if timezone:
                timezone = self._validate_timezone(timezone)
                if not timezone:
                    return await self.send_response(
                        ctx_or_interaction,
                        "올바른 시간대를 입력해줘"
                    )

            current_time = self._get_current_time(timezone)
            await self._send_time_embed(ctx_or_interaction, current_time, timezone or 'Asia/Seoul')
        except Exception as e:
            await self._handle_time_error(ctx_or_interaction, timezone, str(e))

    def _validate_timezone(self, timezone: str) -> Optional[str]:
        """Validate timezone string"""
        try:
            pytz.timezone(timezone)
            return timezone
        except pytz.exceptions.UnknownTimeZoneError:
            return None

    def _get_current_time(self, timezone: Optional[str] = None) -> datetime:
        """Get current time in specified timezone"""
        tz = pytz.timezone(timezone or 'Asia/Seoul')
        return datetime.now(tz)

    async def _send_time_embed(
        self, 
        ctx_or_interaction: CommandContext, 
        current_time: datetime, 
        timezone: str
    ) -> None:
        """Send embed with time information"""
        user_name = self.get_user_name(ctx_or_interaction)
        embed = discord.Embed(
            title="🕒 세계 시간",
            description=f"{user_name}가 요청한 현재 시간 정보야.",
            color=INFO_COLOR
        )
        embed.add_field(name="시간대", value=timezone, inline=True)
        embed.add_field(name="현재 시간", value=current_time.strftime("%Y-%m-%d %H:%M:%S"), inline=True)

        await self.send_response(ctx_or_interaction, embed=embed)

    async def _handle_time_error(
        self, 
        ctx_or_interaction: CommandContext, 
        timezone: Optional[str], 
        error_msg: str
    ) -> None:
        """Handle errors in time command"""
        logger.error(f"Error handling time for timezone {timezone}: {error_msg}")
        user_name = self.get_user_name(ctx_or_interaction)
        await self.send_response(
            ctx_or_interaction,
            f"{user_name}, 시간 정보를 처리하는데 실패했어",
            ephemeral=True
        )

    # Weather commands have been removed
    # If you need to re-enable weather functionality in the future,
    # please check the git history for the implementation

    @discord.app_commands.command(name="exchange", description="환율 정보를 보여줘")
    async def exchange_slash(
        self, 
        interaction: discord.Interaction, 
        currency: Optional[str] = None
    ) -> None:
        """Slash command for exchange rates"""
        await self._handle_exchange(interaction, currency)

    @commands.command(
        name="환율",
        help="현재 환율 정보를 보여줄게",
        brief="환율 확인",
        aliases=["exchange"],
        description="주요 통화의 현재 환율 정보를 보여줘.\n"
        "특정 통화를 지정하면 해당 통화의 환율만 보여줄거야.\n"
        "사용법:\n"
        "• 뮤 환율 [통화코드]\n"
        "• pt exchange [통화코드]\n"
        "예시:\n"
        "• 뮤 환율\n"
        "• 뮤 환율 USD\n"
        "• pt exchange EUR",
    )
    async def exchange_prefix(
        self, 
        ctx: commands.Context, 
        currency: Optional[str] = None
    ) -> None:
        """Prefix command for exchange rates"""
        await self._handle_exchange(ctx, currency)

    @command_handler()
    async def _handle_exchange(
        self, 
        ctx_or_interaction: CommandContext, 
        currency: Optional[str] = None
    ) -> None:
        """Handle exchange rate request"""
        try:
            self._check_api_state('exchange')
            
            processing_msg = None
            try:
                # Show processing message
                processing_msg = await self.send_response(
                    ctx_or_interaction,
                    "환율 정보를 가져오고 있어...",
                    ephemeral=True
                )

                rates = await self.api.exchange.get_exchange_rates()
                if currency:
                    await self._send_single_rate(ctx_or_interaction, currency.upper(), rates)
                else:
                    await self._send_all_rates(ctx_or_interaction, rates)
            except Exception as e:
                await self._handle_exchange_error(ctx_or_interaction, currency, str(e))
            finally:
                if processing_msg:
                    try:
                        await processing_msg.delete()
                    except Exception as e:
                        logger.error(f"Error deleting processing message: {e}")
        except Exception as e:
            await self._handle_exchange_error(ctx_or_interaction, currency, str(e))

    async def _send_single_rate(
        self, 
        ctx_or_interaction: CommandContext, 
        currency: str, 
        rates: Dict[str, float]
    ) -> None:
        """Send exchange rate for single currency"""
        if currency not in rates:
            return await self.send_response(
                ctx_or_interaction,
                f"지원하지 않는 통화인 것 같아: {currency}"
            )

        rate = rates[currency]
        embed = discord.Embed(
            title=f"💱 {currency} 환율",
            description=f"1 {currency} = {rate:,.2f} KRW",
            color=INFO_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed)

    async def _send_all_rates(
        self, 
        ctx_or_interaction: CommandContext, 
        rates: Dict[str, float]
    ) -> None:
        """Send exchange rates for all supported currencies"""
        embed = discord.Embed(
            title="💱 주요 통화 환율",
            color=INFO_COLOR
        )
        
        for currency in ['USD', 'EUR', 'JPY', 'CNY', 'GBP']:
            if currency in rates:
                rate = rates[currency]
                embed.add_field(
                    name=currency,
                    value=f"{rate:,.2f} KRW",
                    inline=True
                )

        await self.send_response(ctx_or_interaction, embed=embed)

    async def _handle_exchange_error(
        self, 
        ctx_or_interaction: CommandContext, 
        currency: Optional[str], 
        error_msg: str
    ) -> None:
        """Handle errors in exchange rate command"""
        logger.error(f"Error getting exchange rates: {error_msg}")
        user_name = self.get_user_name(ctx_or_interaction)
        await self.send_response(
            ctx_or_interaction,
            f"이런, {user_name}! 환율 정보를 가져오는데 실패했어. 서버에 일시적인 문제가 있는 것 같아. 조금 있다가 다시 해볼래?",
            ephemeral=True
        )

    @commands.command(
        name="던파",
        aliases=["dnf", "df"],
        help="던전앤파이터 캐릭터 검색 (현재 비활성화)",
        brief="던파 캐릭터 검색",
        description="던전앤파이터 캐릭터의 정보를 검색합니다 (현재 비활성화)"
    )
    async def search_dnf(
        self,
        ctx: commands.Context,
        character_name: str = None,
        server_name: str = "all"
    ) -> None:
        """던전앤파이터 캐릭터의 정보를 검색합니다"""
        
        # Check if character name is provided
        if not character_name:
            await ctx.send("캐릭터 이름을 입력해주세요. 예: `뮤 던파 캐릭터이름`")
            return
        
        # Send disabled message
        disabled_embed = discord.Embed(
            title="⚠️ 기능 비활성화",
            description=(
                "던전앤파이터 캐릭터 검색 기능이 현재 비활성화되어 있습니다.\n"
                "더 정확한 데미지 계산을 위해 업데이트 중입니다.\n"
                "추후 업데이트를 통해 다시 제공될 예정입니다."
            ),
            color=discord.Color.orange()
        )
        disabled_embed.add_field(
            name="대체 방법",
            value=(
                "캐릭터 정보 확인은 아래 사이트를 이용해주세요:\n"
                "• [네오플 던전앤파이터](https://df.nexon.com/)\n"
                "• [던담](https://dundam.xyz/)"
            ),
            inline=False
        )
        await ctx.send(embed=disabled_embed)
