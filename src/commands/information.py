import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Union, cast

import discord
import pytz
from discord.ext import commands
from discord.ext.commands import Context

from src.services.api import APIService
from src.utils.decorators import command_handler
from src.utils.constants import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR
from src.commands.base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.api_types import GameInfo, CountryInfo, WeatherInfo
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

    @discord.app_commands.command(name="population", description="국가의 인구수를 알려드립니다")
    async def population_slash(self, interaction: discord.Interaction, country_name: str) -> None:
        """Slash command version"""
        await self._handle_population(interaction, country_name)

    @commands.command(
        name="인구",
        help="국가의 인구수를 알려줍니다",
        brief="인구 확인",
        aliases=["population"],
        description=(
            "국가의 인구, 수도, 지역 정보를 보여줍니다.\n"
            "사용법: !!인구 [국가명]\n"
            "예시: !!인구 South Korea"
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
        if not self._validate_country_name(country_name):
            return await self.send_response(
                ctx_or_interaction, "국가 이름을 2글자 이상 입력해주세요..."
            )

        processing_msg = None
        try:
            processing_msg = await self.send_response(
                ctx_or_interaction, "국가 정보를 검색중입니다..."
            )
            country = await self._get_country_info(country_name)
            await self._send_country_embed(ctx_or_interaction, country, processing_msg)
        except Exception as e:
            await self._handle_population_error(ctx_or_interaction, country_name, str(e))
        finally:
            if processing_msg:
                await processing_msg.delete()

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
            processing_msg: Optional processing message to delete
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
        if processing_msg:
            await processing_msg.delete()

    async def _handle_population_error(
        self, 
        ctx_or_interaction: CommandContext, 
        country_name: str, 
        error_msg: str
    ) -> None:
        """Handle errors in population command"""
        logger.error(f"Error getting population for {country_name}: {error_msg}")
        await self.send_response(
            ctx_or_interaction,
            f"국가 정보를 가져오는데 실패했습니다: {country_name}"
        )

    @discord.app_commands.command(name="game", description="Steam 게임의 동시접속자 수를 알려드립니다")
    async def game_slash(self, interaction: discord.Interaction, game_name: str) -> None:
        """Slash command for game search"""
        await self._handle_game_search(interaction, game_name)

    @commands.command(
        name="스팀",
        help="스팀 게임의 현재 플레이어 수를 알려줍니다",
        brief="스팀 게임 정보",
        aliases=["steam"],
        description=(
            "스팀 게임의 현재 플레이어 수와 정보를 보여줍니다.\n"
            "사용법: !!스팀 [게임명]\n"
            "예시:\n"
            "• !!스팀 Lost Ark\n"
            "• !!스팀 PUBG\n"
            "※ 정확한 게임명을 입력하면 더 좋은 결과를 얻을 수 있습니다."
        ),
    )
    async def steam_prefix(self, ctx: commands.Context, *, game_name: str = None):
        """Prefix command version"""
        await self._handle_steam(ctx, game_name)

    @command_handler()
    async def _handle_game_search(
        self, 
        ctx_or_interaction: CommandContext, 
        game_name: Optional[str] = None
    ) -> None:
        """Handle game search request"""
        if not self._validate_game_name(game_name):
            return await self.send_response(
                ctx_or_interaction,
                "게임 이름을 2글자 이상 입력해주세요..."
            )

        try:
            game, similarity, similar_games = await self.api.steam.find_game(game_name)
            if game:
                await self._send_game_embed(ctx_or_interaction, game, similar_games)
            else:
                await self.send_response(
                    ctx_or_interaction,
                    f"게임을 찾을 수 없습니다: {game_name}"
                )
        except Exception as e:
            await self._handle_game_error(ctx_or_interaction, game_name, str(e))

    def _validate_game_name(self, game_name: Optional[str]) -> bool:
        """Validate game name input"""
        return bool(game_name and len(game_name.strip()) >= 2)

    @command_handler()
    async def _handle_steam(self, ctx_or_interaction, game_name: str) -> None:
        """Handle Steam game information request

        Args:
            ctx_or_interaction: Command context or interaction
            game_name: Name of the game to search for

        Raises:
            ValueError: If game not found or API error
        """
        try:
            game, similarity, similar_games = await self.api.steam.find_game(game_name)

            if not game:
                await self._send_game_not_found_embed(ctx_or_interaction)
                return

            embed = await self._create_game_embed(game, similar_games)
            await self.send_response(ctx_or_interaction, embed=embed)

        except Exception:
            await self._send_steam_error_embed(ctx_or_interaction)

    async def _send_game_not_found_embed(self, ctx_or_interaction):
        """Send embed for game not found error

        Args:
            ctx_or_interaction: Command context or interaction
        """
        embed = discord.Embed(title="❌ 게임을 찾을 수 없습니다", color=ERROR_COLOR)
        await self.send_response(ctx_or_interaction, embed=embed)

    async def _create_game_embed(
        self, game: dict, similar_games: Optional[List[dict]] = None
    ) -> discord.Embed:
        """Create embed for game information

        Args:
            game: Game information dictionary
            similar_games: Optional list of similar games

        Returns:
            discord.Embed: Formatted embed with game information
        """
        embed = discord.Embed(title=f"🎮 {game['name']}", color=SUCCESS_COLOR)

        if game.get("player_count") is not None:
            embed.add_field(name="현재 플레이어", value=f"{game['player_count']:,}명", inline=True)
            embed.add_field(name="24시간 최고", value=f"{game['peak_24h']:,}명", inline=True)
            embed.add_field(name="7일 최고", value=f"{game['peak_7d']:,}명", inline=True)
            embed.add_field(name="7일 평균", value=f"{game['avg_7d']:,.1f}명", inline=True)

        if similar_games:
            similar_names = "\n".join(g["name"] for g in similar_games)
            embed.add_field(name="비슷한 게임들", value=similar_names, inline=False)

        return embed

    async def _send_steam_error_embed(self, ctx_or_interaction):
        """Send embed for Steam API error

        Args:
            ctx_or_interaction: Command context or interaction
        """
        embed = discord.Embed(
            title="❌ 오류", description="게임 정보를 가져오는데 실패했습니다.", color=ERROR_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed)

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
        await ctx.send(
            f"명령어 사용 제한 중입니다. " f"{error.retry_after:.1f}초 후에 다시 시도해주세요."
        )

    async def _handle_missing_argument_error(self, ctx):
        """Handle missing argument errors

        Args:
            ctx: Command context
        """
        await ctx.send(
            f"필수 입력값이 누락되었습니다. " f"`!!help {ctx.command}` 로 사용법을 확인해주세요."
        )

    async def _handle_unexpected_error(self, ctx, error):
        """Handle unexpected errors

        Args:
            ctx: Command context
            error: The unexpected error
        """
        logger.error(f"Unexpected error in {ctx.command}: {error}")
        error_messages = [
            "예상치 못한 오류가 발생했습니다.",
            "가능한 해결 방법:",
            "• 잠시 후 다시 시도",
            "• 명령어 사용법 확인 (`!!help` 명령어 사용)",
            "• 봇 관리자에게 문의",
        ]
        await ctx.send("\n".join(error_messages))

    @commands.command(
        name="시간",
        help="세계 시간을 변환합니다",
        brief="시간 변환",
        aliases=["time"],
        description="한국 시간과 세계 각국의 시간을 변환합니다.\n"
        "사용법:\n"
        "!!시간  -> 주요 도시 시간 표시\n"
        "!!시간 US/Pacific  -> 특정 지역 시간 변환\n"
        "!!시간 US/Pacific 09:00  -> 특정 시간 변환",
    )
    async def time_prefix(self, ctx, timezone: str = None, time_str: str = None):
        """Convert time between timezones
        Examples:
        !!시간  # Show all timezones
        !!시간 US/Pacific  # Convert current KR time to PST
        !!시간 US/Pacific 09:00  # Convert PST 09:00 to KR time
        """
        await self._handle_time(ctx, timezone, time_str)

    @discord.app_commands.command(name="time", description="세계 시간을 보여줍니다")
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
                        "올바른 시간대를 입력해주세요"
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
        """Send time information embed"""
        embed = discord.Embed(
            title=f"🕒 {timezone} 현재 시각",
            description=current_time.strftime("%Y-%m-%d %H:%M:%S"),
            color=INFO_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed)

    async def _handle_time_error(
        self, 
        ctx_or_interaction: CommandContext, 
        timezone: Optional[str], 
        error_msg: str
    ) -> None:
        """Handle errors in time command"""
        logger.error(f"Error handling time for timezone {timezone}: {error_msg}")
        await self.send_response(
            ctx_or_interaction,
            "시간 정보를 처리하는데 실패했습니다"
        )

    @discord.app_commands.command(name="weather", description="도시의 날씨를 알려드립니다")
    async def weather_slash(self, interaction: discord.Interaction, city_name: str) -> None:
        """Slash command for weather"""
        await self._handle_weather(interaction, city_name)

    @command_handler()
    async def _handle_weather(
        self, 
        ctx_or_interaction: CommandContext, 
        city_name: Optional[str] = None
    ) -> None:
        """Handle weather information request"""
        if not self._validate_city_name(city_name):
            return await self.send_response(
                ctx_or_interaction, 
                "도시 이름을 2글자 이상 입력해주세요..."
            )

        try:
            weather_info = await self.api.weather.get_weather(city_name)
            await self._send_weather_embed(ctx_or_interaction, weather_info)
        except Exception as e:
            await self._handle_weather_error(ctx_or_interaction, city_name, str(e))

    def _validate_city_name(self, city_name: Optional[str]) -> bool:
        """Validate city name input"""
        return bool(city_name and len(city_name.strip()) >= 2)

    async def _send_weather_embed(
        self, 
        ctx_or_interaction: CommandContext, 
        weather: WeatherInfo
    ) -> None:
        """Create and send weather information embed"""
        temp = weather['main'].get('temp', 0)
        feels_like = weather['main'].get('feels_like', 0)
        humidity = weather['main'].get('humidity', 0)
        description = weather['weather'][0].get('description', '') if weather['weather'] else ''

        embed = discord.Embed(
            title=f"🌤️ {weather['name']}의 날씨",
            color=INFO_COLOR
        )
        embed.add_field(name="온도", value=f"{temp}°C", inline=True)
        embed.add_field(name="체감 온도", value=f"{feels_like}°C", inline=True)
        embed.add_field(name="습도", value=f"{humidity}%", inline=True)
        embed.add_field(name="날씨", value=description, inline=False)

        await self.send_response(ctx_or_interaction, embed=embed)

    async def _handle_weather_error(
        self, 
        ctx_or_interaction: CommandContext, 
        city_name: str, 
        error_msg: str
    ) -> None:
        """Handle errors in weather command"""
        logger.error(f"Error getting weather for {city_name}: {error_msg}")
        await self.send_response(
            ctx_or_interaction,
            f"날씨 정보를 가져오는데 실패했습니다: {city_name}"
        )

    @discord.app_commands.command(name="exchange", description="환율 정보를 보여줍니다")
    async def exchange_slash(
        self, 
        interaction: discord.Interaction, 
        currency: Optional[str] = None
    ) -> None:
        """Slash command for exchange rates"""
        await self._handle_exchange(interaction, currency)

    @commands.command(
        name="환율",
        help="현재 환율 정보를 보여줍니다",
        brief="환율 확인",
        aliases=["exchange"],
        description="주요 통화의 현재 환율 정보를 보여줍니다.\n"
        "특정 통화를 지정하면 해당 통화의 환율만 보여줍니다.\n"
        "사용법: !!환율 [통화코드]",
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
            rates = await self.api.exchange.get_exchange_rates()
            if currency:
                await self._send_single_rate(ctx_or_interaction, currency.upper(), rates)
            else:
                await self._send_all_rates(ctx_or_interaction, rates)
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
                f"지원하지 않는 통화입니다: {currency}"
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
        await self.send_response(
            ctx_or_interaction,
            "환율 정보를 가져오는데 실패했습니다"
        )
