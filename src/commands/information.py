from discord.ext import commands
import discord
from ..services.api import APIService
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class InformationCommands(commands.Cog):
    def __init__(self, api_service: APIService):
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
                    "사용법: !!날씨"
    )
    async def weather_prefix(self, ctx: commands.Context):
        """Prefix command version"""
        await ctx.send("🚧 날씨 기능은 현재 개발 진행중입니다. 조금만 기다려주세요!")

    async def _handle_weather(self, ctx_or_interaction):
        processing_msg = None
        try:
            # Get user name and show processing message
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)

            data = await self.api.get_weather("Seoul")
            
            embed = discord.Embed(title="🌈 서울 현재 날씨", color=discord.Color.blue())
            embed.add_field(name="온도", value=f"{data['main']['temp']}°C", inline=True)
            embed.add_field(name="체감온도", value=f"{data['main']['feels_like']}°C", inline=True)
            embed.add_field(name="습도", value=f"{data['main']['humidity']}%", inline=True)
            embed.add_field(name="날씨", value=data['weather'][0]['description'], inline=False)
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.channel.send(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)
                if processing_msg:
                    await processing_msg.delete()

        except Exception as e:
            logger.error(f"Weather API error: {e}")
            if "Rate limit exceeded" in str(e):
                message = "날씨 API 호출 제한에 도달했습니다. 잠시 후 다시 시도해주세요. (약 1분 후)"
            else:
                error_messages = [
                    "날씨 정보를 가져오는데 실패했습니다.",
                    "가능한 원인:",
                    "• 날씨 API 서비스 장애",
                    "• 네트워크 연결 문제",
                    "• API 호출 제한",
                    "\n잠시 후 다시 시도해주세요."
                ]
                message = "\n".join(error_messages)
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()

    @discord.app_commands.command(name="population", description="국가의 인구수를 알려드립니다")
    async def population_slash(self, interaction: discord.Interaction, country_name: str):
        """Slash command version"""
        await self._handle_population(interaction, country_name)

    @commands.command(name="인구", help="국가의 인구수를 알려줍니다", brief="인구 확인", aliases=["population"], description="국가의 인구, 수도, 지역 정보를 보여줍니다.\n"
                "사용법: !!인구 [국가명]\n"
                "예시:\n"
                "• !!인구 South Korea\n"
                "• !!인구 United States\n"
                "※ 국가명은 영어로 입력해주세요.")
    async def population_prefix(self, ctx: commands.Context, *, country_name: str = None):
        """Prefix command version"""
        await self._handle_population(ctx, country_name)

    async def _handle_population(self, ctx_or_interaction, country_name: str = None):
        processing_msg = None
        try:
            if not country_name or len(country_name.strip()) < 2:
                suggestions = [
                    "국가 이름을 2글자 이상 입력해주세요.",
                    "예시:",
                    "• `/population South Korea` 또는 `!!인구 South Korea`",
                    "• `/population United States` 또는 `!!인구 United States`",
                    "• `/population Japan` 또는 `!!인구 Japan`",
                    "\n참고: 국가명은 영어로 입력해주세요."
                ]
                message = "\n".join(suggestions)
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx_or_interaction.send(message)
                return

            # Get user name and show processing message
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)

            # Sanitize input
            country_name = country_name.strip()[:50]
            country_name = ''.join(c for c in country_name if c.isalnum() or c.isspace())
            
            country = await self.api.get_country_info(country_name)
            
            embed = discord.Embed(
                title=f"🌏 {country['name']['official']}",
                color=discord.Color.green()
            )
            embed.add_field(name="인구", value=f"{country['population']:,}명", inline=False)
            embed.add_field(name="수도", value=country.get('capital', ['정보없음'])[0], inline=True)
            embed.add_field(name="지역", value=country.get('region', '정보없음'), inline=True)
            
            if 'flags' in country and 'png' in country['flags']:
                embed.set_thumbnail(url=country['flags']['png'])
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.channel.send(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)
                if processing_msg:
                    await processing_msg.delete()

        except Exception as e:
            logger.error(f"Population API error for '{country_name}': {e}")
            if "Rate limit exceeded" in str(e):
                message = "API 호출 제한에 도달했습니다. 잠시 후 다시 시도해주세요. (약 1분 후)"
            else:
                error_messages = [
                    f"'{country_name}' 국가를 찾을 수 없습니다.",
                    "다음 사항을 확인해주세요:",
                    "• 영어로 국가명을 입력했는지 확인 (예: 'Korea' ✅, '한국' ❌)",
                    "• 정확한 국가명을 사용했는지 확인 (예: 'South Korea' ✅, 'Korea' ❌)",
                    "• 오타가 없는지 확인",
                    "\n예시: South Korea, United States, Japan, China 등"
                ]
                message = "\n".join(error_messages)
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()

    @discord.app_commands.command(name="steam", description="스팀 게임의 현재 플레이어 수를 알려드립니다")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def steam_slash(self, interaction: discord.Interaction, game_name: str):
        """Slash command version"""
        await self._handle_steam(interaction, game_name)

    @commands.command(name="스팀", help="스팀 게임의 현재 플레이어 수를 알려줍니다", brief="스팀 게임 정보", aliases=["steam"], description="스팀 게임의 현재 플레이어 수와 정보를 보여줍니다.\n"
                "사용법: !!스팀 [게임명]\n"
                "예시:\n"
                "• !!스팀 Lost Ark\n"
                "• !!스팀 PUBG\n"
                "※ 정확한 게임명을 입력하면 더 좋은 결과를 얻을 수 있습니다.")
    async def steam_prefix(self, ctx: commands.Context, *, game_name: str = None):
        """Prefix command version"""
        await self._handle_steam(ctx, game_name)

    async def _handle_steam(self, ctx_or_interaction, game_name: str = None):
        processing_msg = None
        try:
            if not game_name or len(game_name.strip()) < 2:
                message = "게임 이름을 2글자 이상 입력해주세요.\n예시: `/steam Lost Ark` 또는 `!!스팀 로스트아크`"
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx_or_interaction.send(message)
                return

            # Get user name and show processing message
            user_name = ctx_or_interaction.user.display_name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.display_name
            processing_text = f"{user_name}님의 명령어를 처리중입니다..."

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer(ephemeral=True)
                await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
            else:
                processing_msg = await ctx_or_interaction.send(processing_text)

            game, similarity, similar_matches = await self.api.find_game(game_name)
            
            # If we got a list of similar matches
            if similar_matches:
                embed = discord.Embed(
                    title="비슷한 게임이 여러 개 발견되었습니다",
                    description="아래 게임 중 하나를 선택하여 다시 검색해주세요:",
                    color=discord.Color.blue()
                )
                
                for i, game in enumerate(similar_matches, 1):
                    name = game.get('korean_name', game['name'])
                    if 'korean_name' in game and game['korean_name'] != game['name']:
                        name = f"{game['korean_name']} ({game['name']})"
                    embed.add_field(
                        name=f"{i}. {name}", 
                        value=f"ID: {game['appid']}", 
                        inline=False
                    )
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.channel.send(embed=embed)
                else:
                    await ctx_or_interaction.send(embed=embed)
                if processing_msg:
                    await processing_msg.delete()
                return
            
            # If no game found
            if not game:
                suggestions = [
                    f"'{game_name}'에 해당하는 게임을 찾을 수 없습니다.",
                    "다음과 같은 방법을 시도해보세요:",
                    "• 정확한 게임 이름으로 검색 (예: 'PUBG' 대신 'PUBG: BATTLEGROUNDS')",
                    "• 영문 이름으로 검색 (예: '로아' 대신 'Lost Ark')",
                    "• 전체 이름으로 검색 (예: 'LOL' 대신 'League of Legends')"
                ]
                message = "\n".join(suggestions)
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.followup.send(message, ephemeral=True)
                else:
                    await ctx_or_interaction.send(message)
                if processing_msg:
                    await processing_msg.delete()
                return
            
            try:
                player_count = await self.api.get_player_count(game['appid'])
            except Exception as e:
                if "Rate limit exceeded" in str(e):
                    message = "Steam API 호출 제한에 도달했습니다. 잠시 후 다시 시도해주세요. (약 1분 후)"
                else:
                    logger.error(f"Player count error for game {game['name']}: {e}")
                    message = "플레이어 수 정보를 가져오는데 실패했습니다. 하지만 게임 정보는 표시됩니다."
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.followup.send(message, ephemeral=True)
                else:
                    await ctx_or_interaction.send(message)
                player_count = None

            # Update title to show both names if available
            title = game.get('korean_name', game['name'])
            if 'korean_name' in game and game['korean_name'] != game['name']:
                title = f"{game['korean_name']} ({game['name']})"
            
            embed = discord.Embed(
                title=title,
                url=f"https://store.steampowered.com/app/{game['appid']}",
                color=discord.Color.blue()
            )
            
            if player_count > 0:
                embed.add_field(name="현재 플레이어 수", value=f"{player_count:,}명")
            else:
                embed.add_field(name="현재 플레이어 수", value="정보 없음")
            
            if similarity < 100:
                embed.add_field(
                    name="참고", 
                    value=f"입력하신 '{game_name}'와(과) 가장 유사한 게임을 찾았습니다.\n"
                          f"정확도: {similarity}%",
                    inline=False
                )
            
            embed.set_thumbnail(url=f"https://cdn.cloudflare.steamstatic.com/steam/apps/{game['appid']}/header.jpg")
            
            # Update embed to show all available translations
            if 'localized_names' in game:
                names_list = []
                for lang_data in game['localized_names'].values():
                    names_list.append(f"{lang_data['language']}: {lang_data['name']}")
                
                if names_list:
                    embed.add_field(
                        name="다른 언어",
                        value="\n".join(names_list),
                        inline=False
                    )
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.channel.send(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)
                if processing_msg:
                    await processing_msg.delete()
            
        except Exception as e:
            logger.error(f"Steam search error for '{game_name}': {e}")
            error_messages = [
                "게임 검색 중 오류가 발생했습니다.",
                "가능한 원인:",
                "• Steam 서비스 일시적 장애",
                "• 네트워크 연결 문제",
                "• API 호출 제한",
                "\n나중에 다시 시도해주세요."
            ]
            message = "\n".join(error_messages)
            
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message)
            if processing_msg:
                await processing_msg.delete()
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore command not found errors
        
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"명령어 사용 제한 중입니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"필수 입력값이 누락되었습니다. `!!help {ctx.command}` 로 사용법을 확인해주세요.")
        else:
            logger.error(f"Unexpected error in {ctx.command}: {error}")
            error_messages = [
                "예상치 못한 오류가 발생했습니다.",
                "가능한 해결 방법:",
                "• 잠시 후 다시 시도",
                "• 명령어 사용법 확인 (`!!help` 명령어 사용)",
                "• 봇 관리자에게 문의"
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
                    "!!시간 US/Pacific 09:00  -> 특정 시간 변환"
    )
    async def time_prefix(self, ctx, timezone: str = None, time_str: str = None):
        """Convert time between timezones
        Examples:
        !!시간  # Show all timezones
        !!시간 US/Pacific  # Convert current KR time to PST
        !!시간 US/Pacific 09:00  # Convert PST 09:00 to KR time
        """
        await self._handle_time(ctx, timezone, time_str)

    @discord.app_commands.command(
        name="time",
        description="세계 시간을 보여줍니다"
    )
    async def time_slash(self, interaction: discord.Interaction, timezone: str = None, time: str = None):
        """Slash command version of time conversion"""
        await self._handle_time(interaction, timezone, time)

    async def _handle_time(self, ctx_or_interaction, timezone: str = None, time_str: str = None):
        try:
            kr_tz = pytz.timezone('Asia/Seoul')
            kr_time = datetime.now(kr_tz)

            embed = discord.Embed(
                title="🕐 세계 시간",
                color=discord.Color.blue(),
                timestamp=kr_time
            )

            if timezone and time_str:
                try:
                    # Parse the input time
                    try:
                        # Try parsing time-only format (HH:MM)
                        time_parts = time_str.split(':')
                        hour = int(time_parts[0])
                        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                        
                        # Use today's date with the specified time
                        target_tz = pytz.timezone(timezone)
                        current = datetime.now(target_tz)
                        input_time = current.replace(hour=hour, minute=minute)
                        
                    except ValueError:
                        raise ValueError("시간 형식이 잘못되었습니다. HH:MM 형식으로 입력해주세요 (예: 09:00)")

                    # Convert to Korean time
                    kr_time = input_time.astimezone(kr_tz)
                    
                    embed.add_field(
                        name=f"{timezone} 시간",
                        value=input_time.strftime("%Y-%m-%d %H:%M"),
                        inline=True
                    )
                    embed.add_field(
                        name="한국 시간",
                        value=kr_time.strftime("%Y-%m-%d %H:%M"),
                        inline=True
                    )
                    
                except pytz.exceptions.UnknownTimeZoneError:
                    raise ValueError(f"지원하지 않는 시간대입니다: {timezone}")
                
            elif timezone:
                # Original functionality (KR → Target)
                try:
                    target_tz = pytz.timezone(timezone)
                    target_time = kr_time.astimezone(target_tz)
                    embed.add_field(
                        name="한국 시간",
                        value=kr_time.strftime("%Y-%m-%d %H:%M"),
                        inline=True
                    )
                    embed.add_field(
                        name=f"{timezone} 시간",
                        value=target_time.strftime("%Y-%m-%d %H:%M"),
                        inline=True
                    )
                except pytz.exceptions.UnknownTimeZoneError:
                    raise ValueError(f"지원하지 않는 시간대입니다: {timezone}")
            else:
                # Show common timezones
                common_timezones = {
                    'US/Pacific': 'PST',
                    'US/Eastern': 'EST',
                    'Europe/London': 'UK',
                    'Europe/Paris': 'EU',
                    'Australia/Sydney': 'SYD',
                }
                
                embed.add_field(
                    name="한국 시간",
                    value=kr_time.strftime("%Y-%m-%d %H:%M"),
                    inline=False
                )
                
                for tz_name, display_name in common_timezones.items():
                    target_tz = pytz.timezone(tz_name)
                    target_time = kr_time.astimezone(target_tz)
                    embed.add_field(
                        name=display_name,
                        value=target_time.strftime("%Y-%m-%d %H:%M"),
                        inline=True
                    )

                # Add usage examples
                embed.add_field(
                    name="사용법",
                    value="• `!!시간` - 모든 시간대 표시\n"
                          "• `!!시간 US/Pacific` - 한국→PST 변환\n"
                          "• `!!시간 US/Pacific 09:00` - PST→한국 변환",
                    inline=False
                )

            # Send response
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)

        except Exception as e:
            error_msg = f"시간 변환에 실패했습니다: {str(e)}"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(error_msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(error_msg) 