import logging
from datetime import datetime
from typing import List, Optional

import discord
import pytz
from discord.ext import commands

from ..services.api import APIService
from ..utils.decorators import command_handler
from .base_commands import BaseCommands

logger = logging.getLogger(__name__)

# Constants for embed colors
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
INFO_COLOR = discord.Color.blue()


class InformationCommands(BaseCommands):
    """Commands for retrieving various information"""

    def __init__(self, api_service: APIService):
        """Initialize information commands

        Args:
            api_service: API service instance for external data
        """
        self.api = api_service

    @discord.app_commands.command(name="weather", description="서울의 현재 날씨를 알려드립니다")
    async def weather_slash(self, interaction: discord.Interaction):
        """Slash command version"""
        await self._handle_weather(interaction)

    @commands.command(
        name="날씨",
        help="서울의 현재 날씨를 알려줍니다 (개발중)",
        brief="날씨 확인",
        aliases=["weather"],
        description="서울의 현재 날씨 정보를 보여줍니다.\n"
        "※ 현재 개발 진행중인 기능입니다.\n"
        "사용법: !!날씨",
    )
    async def weather_prefix(self, ctx: commands.Context):
        """Prefix command version"""
        await ctx.send("🚧 날씨 기능은 현재 개발 진행중입니다. 조금만 기다려주세요!")

    @command_handler()
    async def _handle_weather(self, ctx_or_interaction) -> None:
        """Handle weather information request

        Args:
            ctx_or_interaction: Command context or interaction

        Raises:
            ValueError: If weather data cannot be retrieved
        """
        try:
            weather_data = await self._get_weather_data()
            embed = await self._create_weather_embed(weather_data)
            await self.send_response(ctx_or_interaction, embed=embed)

        except Exception:
            await self._send_weather_error_embed(ctx_or_interaction)

    async def _get_weather_data(self) -> dict:
        """Get weather data from API

        Returns:
            dict: Weather data for Seoul

        Raises:
            ValueError: If API request fails
        """
        return await self.api.weather.get_weather("Seoul")

    async def _create_weather_embed(self, weather_data: dict) -> discord.Embed:
        """Create embed for weather information

        Args:
            weather_data: Weather data from API

        Returns:
            discord.Embed: Formatted embed with weather information
        """
        embed = discord.Embed(title="🌤️ 서울 날씨", color=INFO_COLOR)

        # Add temperature fields
        embed.add_field(name="온도", value=f"{weather_data['main']['temp']}°C")
        embed.add_field(name="체감", value=f"{weather_data['main']['feels_like']}°C")
        embed.add_field(name="습도", value=f"{weather_data['main']['humidity']}%")

        return embed

    async def _send_weather_error_embed(self, ctx_or_interaction):
        """Send error embed for weather command

        Args:
            ctx_or_interaction: Command context or interaction
        """
        embed = discord.Embed(
            title="❌ 오류", description="날씨 정보를 가져오는데 실패했습니다.", color=ERROR_COLOR
        )
        await self.send_response(ctx_or_interaction, embed=embed)

    @discord.app_commands.command(name="population", description="국가의 인구수를 알려드립니다")
    async def population_slash(self, interaction: discord.Interaction, country_name: str):
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
    async def _handle_population(self, ctx_or_interaction, country_name: str = None):
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
            await self._send_country_embed(ctx_or_interaction, country)
        except Exception as e:
            await self._handle_population_error(ctx_or_interaction, country_name, e)
        finally:
            if processing_msg:
                await processing_msg.delete()

    def _validate_country_name(self, country_name: str) -> bool:
        """Validate country name input

        Args:
            country_name: Name to validate

        Returns:
            bool: True if name is valid
        """
        return country_name and len(country_name.strip()) >= 2

    async def _get_country_info(self, country_name: str):
        """Get country information from API

        Args:
            country_name: Name of country to look up

        Returns:
            dict: Country information

        Raises:
            ValueError: If country not found or API error
        """
        # Sanitize input
        country_name = country_name.strip()[:50]
        country_name = "".join(c for c in country_name if c.isalnum() or c.isspace())
        return await self.api.population.get_country_info(country_name)

    async def _send_country_embed(self, ctx_or_interaction, country, processing_msg=None):
        """Send embed with country information

        Args:
            ctx_or_interaction: Command context or interaction
            country: Country information dictionary
            processing_msg: Optional processing message to delete
        """
        embed = discord.Embed(
            title=f"🌏 {country['name']['official']}", color=discord.Color.green()
        )
        embed.add_field(name="인구", value=f"{country['population']:,}명", inline=False)
        embed.add_field(name="수도", value=country.get("capital", ["정보없음"])[0], inline=True)
        embed.add_field(name="지역", value=country.get("region", "정보없음"), inline=True)

        if "flags" in country and "png" in country["flags"]:
            embed.set_thumbnail(url=country["flags"]["png"])

        await self._send_response(ctx_or_interaction, embed=embed)
        if processing_msg:
            await processing_msg.delete()

    async def _handle_population_error(
        self, ctx_or_interaction, country_name, error, processing_msg=None
    ):
        """Handle errors in population command

        Args:
            ctx_or_interaction: Command context or interaction
            country_name: Name of country that caused error
            error: The error that occurred
            processing_msg: Optional processing message to delete
        """
        logger.error(f"Population API error for '{country_name}': {error}")

        if "Rate limit exceeded" in str(error):
            message = "API 호출 제한에 도달했습니다. 잠시 후 다시 시도해주세요. (약 1분 후)"
        else:
            message = self._get_country_error_message(country_name)

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.followup.send(message, ephemeral=True)
        else:
            await ctx_or_interaction.send(message)
            if processing_msg:
                await processing_msg.delete()

    def _get_country_error_message(self, country_name: str) -> str:
        """Get error message for country lookup failure

        Args:
            country_name: Name of country that failed

        Returns:
            str: Formatted error message
        """
        error_messages = [
            f"'{country_name}' 국가를 찾을 수 없습니다.",
            "다음 사항을 확인해주세요:",
            "• 영어로 국가명을 입력했는지 확인 (예: 'Korea' ✅, '한국' ❌)",
            "• 정확한 국가명을 사용했는지 확인 (예: 'South Korea' ✅, 'Korea' ❌)",
            "• 오타가 없는지 확인",
            "\n예시: South Korea, United States, Japan, China 등",
        ]
        return "\n".join(error_messages)

    @discord.app_commands.command(
        name="steam", description="스팀 게임의 현재 플레이어 수를 알려드립니다"
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def steam_slash(self, interaction: discord.Interaction, game_name: str):
        """Slash command version"""
        await self._handle_steam(interaction, game_name)

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
            embed.add_field(name="현재 플레이어", value=f"{game['player_count']:,}명")

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
        self, interaction: discord.Interaction, timezone: str = None, time: str = None
    ):
        """Slash command version of time conversion"""
        await self._handle_time(interaction, timezone, time)

    async def _handle_time(self, ctx_or_interaction, timezone: str = None, time_str: str = None):
        """Handle time conversion request

        Args:
            ctx_or_interaction: Command context or interaction
            timezone: Optional timezone to convert to/from
            time_str: Optional time string to convert

        Raises:
            ValueError: If timezone is invalid or time format is incorrect
        """
        try:
            kr_tz = pytz.timezone("Asia/Seoul")
            kr_time = datetime.now(kr_tz)

            embed = discord.Embed(
                title="🕐 세계 시간", color=discord.Color.blue(), timestamp=kr_time
            )

            if timezone and time_str:
                await self._handle_specific_time_conversion(embed, timezone, time_str, kr_tz)
            elif timezone:
                await self._handle_timezone_conversion(embed, timezone, kr_time)
            else:
                await self._show_common_timezones(embed, kr_time)

            await self._send_response(ctx_or_interaction, embed=embed)

        except ValueError as e:
            raise e  # Re-raise user input errors
        except Exception as e:
            logger.error(f"Unexpected error in time command: {e}")
            raise ValueError("예상치 못한 오류가 발생했습니다") from e

    async def _handle_specific_time_conversion(self, embed, timezone: str, time_str: str, kr_tz):
        """Handle conversion of specific time in a timezone

        Args:
            embed: Discord embed to add fields to
            timezone: Timezone to convert from
            time_str: Time string to convert
            kr_tz: Korean timezone object
        """
        try:
            input_time = self._parse_time_string(time_str)
            target_tz = pytz.timezone(timezone)
            current = datetime.now(target_tz)
            input_time = current.replace(hour=input_time[0], minute=input_time[1])
            kr_time = input_time.astimezone(kr_tz)

            embed.add_field(
                name=f"{timezone} 시간", value=input_time.strftime("%Y-%m-%d %H:%M"), inline=True
            )
            embed.add_field(name="한국 시간", value=kr_time.strftime("%Y-%m-%d %H:%M"), inline=True)

        except pytz.exceptions.UnknownTimeZoneError as e:
            raise ValueError(f"지원하지 않는 시간대입니다: {timezone}") from e

    def _parse_time_string(self, time_str: str) -> tuple[int, int]:
        """Parse time string into hour and minute

        Args:
            time_str: Time string in HH:MM format

        Returns:
            tuple[int, int]: Hour and minute

        Raises:
            ValueError: If time format is invalid
        """
        try:
            time_parts = time_str.split(":")
            if len(time_parts) != 2:
                raise ValueError("시간은 HH:MM 형식이어야 합니다")

            hour = int(time_parts[0])
            minute = int(time_parts[1])

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("올바른 시간 범위가 아닙니다")

            return hour, minute

        except (ValueError, IndexError) as e:
            raise ValueError(
                "시간 형식이 잘못되었습니다. " "HH:MM 형식으로 입력해주세요 (예: 09:00)"
            ) from e

    async def _handle_timezone_conversion(self, embed, timezone: str, kr_time):
        """Handle conversion between KR and target timezone

        Args:
            embed: Discord embed to add fields to
            timezone: Target timezone
            kr_time: Korean current time
        """
        try:
            target_tz = pytz.timezone(timezone)
            target_time = kr_time.astimezone(target_tz)
            embed.add_field(name="한국 시간", value=kr_time.strftime("%Y-%m-%d %H:%M"), inline=True)
            embed.add_field(
                name=f"{timezone} 시간", value=target_time.strftime("%Y-%m-%d %H:%M"), inline=True
            )
        except pytz.exceptions.UnknownTimeZoneError:
            raise ValueError(f"지원하지 않는 시간대입니다: {timezone}")

    async def _show_common_timezones(self, embed, kr_time):
        """Show common timezone conversions

        Args:
            embed: Discord embed to add fields to
            kr_time: Korean current time
        """
        common_timezones = {
            "US/Pacific": "PST",
            "US/Eastern": "EST",
            "Europe/London": "UK",
            "Europe/Paris": "EU",
            "Australia/Sydney": "SYD",
        }

        embed.add_field(name="한국 시간", value=kr_time.strftime("%Y-%m-%d %H:%M"), inline=False)

        for tz_name, display_name in common_timezones.items():
            target_tz = pytz.timezone(tz_name)
            target_time = kr_time.astimezone(target_tz)
            embed.add_field(
                name=display_name, value=target_time.strftime("%Y-%m-%d %H:%M"), inline=True
            )

        # Add usage examples
        embed.add_field(
            name="사용법",
            value="• `!!시간` - 모든 시간대 표시\n"
            "• `!!시간 US/Pacific` - 한국→PST 변환\n"
            "• `!!시간 US/Pacific 09:00` - PST→한국 변환",
            inline=False,
        )

    @discord.app_commands.command(name="exchange", description="환율 정보를 보여줍니다")
    async def exchange_slash(
        self, interaction: discord.Interaction, currency: str = None, amount: float = 1.0
    ):
        """Slash command version of exchange rate conversion"""
        await self._handle_exchange(interaction, currency, amount)

    @commands.command(
        name="환율",
        help="환율 정보를 보여줍니다",
        brief="환율 확인",
        aliases=["exchange"],
        description="KRW와 다른 통화 간의 환율을 보여줍니다.\n"
        "사용법:\n"
        "!!환율  -> 모든 통화 환율 표시\n"
        "!!환율 USD  -> USD 환율 표시\n"
        "!!환율 USD 100  -> 100 USD의 KRW 환산",
    )
    async def exchange_prefix(
        self, ctx: commands.Context, currency: str = None, amount: float = 1.0
    ):
        """Prefix command version of exchange rate conversion"""
        await self._handle_exchange(ctx, currency, amount)

    @command_handler()
    async def _handle_exchange(self, ctx_or_interaction, currency: str = None, amount: float = 1.0):
        """Handle exchange rate conversion command

        Args:
            ctx_or_interaction: Command context or interaction
            currency: Optional currency code to convert
            amount: Amount to convert (default: 1.0)

        Raises:
            ValueError: If amount is invalid or currency not supported
        """
        try:
            self._validate_amount(amount)
            rates = await self._get_exchange_rates()
            embed = await self._create_exchange_embed(rates, currency, amount)
            return await self.send_response(ctx_or_interaction, embed=embed)

        except ValueError as e:
            raise e
        except Exception as e:
            logger.error(f"Exchange rate error: {e}")
            raise ValueError(f"환율 정보를 가져오는데 실패했습니다: {str(e)}")

    def _validate_amount(self, amount: float) -> None:
        """Validate exchange amount

        Args:
            amount: Amount to validate

        Raises:
            ValueError: If amount is invalid
        """
        if amount <= 0:
            raise ValueError("금액은 0보다 커야 합니다")
        if amount > 1000000000:
            raise ValueError("금액이 너무 큽니다 (최대: 1,000,000,000)")

    async def _get_exchange_rates(self):
        """Get current exchange rates

        Returns:
            dict: Exchange rates

        Raises:
            ValueError: If failed to get rates
        """
        return await self.api.exchange.get_exchange_rates()

    async def _create_exchange_embed(self, rates: dict, currency: str = None, amount: float = 1.0):
        """Create embed for exchange rate display

        Args:
            rates: Exchange rates
            currency: Optional specific currency to show
            amount: Amount to convert

        Returns:
            discord.Embed: Formatted embed with exchange rates

        Raises:
            ValueError: If currency is not supported
        """
        embed = discord.Embed(
            title="💱 환율 정보", color=discord.Color.blue(), timestamp=datetime.now()
        )

        if currency:
            await self._add_single_currency_field(embed, rates, currency, amount)
        else:
            await self._add_all_currencies_fields(embed, rates)

        embed.set_footer(text="Data from ExchangeRate-API")
        return embed

    async def _add_single_currency_field(self, embed, rates: dict, currency: str, amount: float):
        """Add field for single currency conversion

        Args:
            embed: Discord embed to add field to
            rates: Exchange rates
            currency: Currency to convert
            amount: Amount to convert

        Raises:
            ValueError: If currency is not supported
        """
        currency_code = currency.upper()
        if currency_code not in rates:
            supported_currencies = ", ".join(rates.keys())
            raise ValueError(
                f"지원하지 않는 통화입니다: {currency}\n" f"지원되는 통화: {supported_currencies}"
            )

        krw_amount = amount * rates[currency_code]
        embed.description = f"{amount:,.2f} {currency_code} = {krw_amount:,.2f} KRW"

    async def _add_all_currencies_fields(self, embed, rates: dict):
        """Add fields for all currencies

        Args:
            embed: Discord embed to add fields to
            rates: Exchange rates
        """
        base_amount = 1000
        for curr, rate in rates.items():
            foreign_amount = base_amount / rate
            embed.add_field(
                name=curr,
                value=f"{base_amount:,.0f} KRW = {foreign_amount:,.2f} {curr}",
                inline=True,
            )
