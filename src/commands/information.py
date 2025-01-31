from discord.ext import commands
import discord
from ..services.api import APIService

class InformationCommands(commands.Cog):
    def __init__(self, api_service: APIService):
        self.api = api_service
    
    @commands.command(name="날씨", help="서울의 현재 날씨를 알려드립니다", aliases=["weather"])
    @commands.cooldown(1, 5, commands.BucketType.user)  # 1 use per 5 seconds per user
    async def weather(self, ctx):
        try:
            data = await self.api.get_weather("Seoul")
            
            embed = discord.Embed(title="🌈 서울 현재 날씨", color=discord.Color.blue())
            embed.add_field(name="온도", value=f"{data['main']['temp']}°C", inline=True)
            embed.add_field(name="체감온도", value=f"{data['main']['feels_like']}°C", inline=True)
            embed.add_field(name="습도", value=f"{data['main']['humidity']}%", inline=True)
            embed.add_field(name="날씨", value=data['weather'][0]['description'], inline=False)
            
            await ctx.send(embed=embed)
        except Exception as e:
            if "Rate limit exceeded" in str(e):
                await ctx.send("잠시 후 다시 시도해주세요. (API 호출 제한)")
            else:
                await ctx.send("날씨 정보를 가져오는데 실패했습니다.")
                print(f"Weather Error: {e}")
    
    @weather.error
    async def weather_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"명령어를 너무 자주 사용하셨습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.")
    
    @commands.command(name="스팀", help="스팀 게임의 현재 플레이어 수를 알려드립니다")
    @commands.cooldown(1, 3, commands.BucketType.user)  # 1 use per 3 seconds per user
    async def steam(self, ctx, *, game_name: str = None):
        try:
            if not game_name or len(game_name.strip()) < 2:
                await ctx.send("게임 이름을 2글자 이상 입력해주세요. (예: !!스팀 로스트아크)")
                return
            
            print(f"\nProcessing steam command for: '{game_name}'")
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
                
                await ctx.send(embed=embed)
                return
            
            # If no game found
            if not game:
                await ctx.send("게임을 찾을 수 없습니다. 다른 검색어로 시도해주세요.")
                return
            
            try:
                player_count = await self.api.get_player_count(game['appid'])
            except Exception as e:
                if "Rate limit exceeded" in str(e):
                    await ctx.send("잠시 후 다시 시도해주세요. (API 호출 제한)")
                    return
                print(f"Player count error: {e}")
                player_count = 0
            
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
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
            print(f"Steam Command Error for query '{game_name}': {e}")
    
    @steam.error
    async def steam_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"명령어를 너무 자주 사용하셨습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.")
    
    @commands.command(name="인구", help="국가의 인구수를 알려드립니다", aliases=["population"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def population(self, ctx, *, country_name: str = None):
        try:
            if not country_name or len(country_name.strip()) < 2:
                await ctx.send("국가 이름을 2글자 이상 입력해주세요. (예: !!인구 South Korea)")
                return

            # Sanitize input
            country_name = country_name.strip()[:50]  # Limit length
            country_name = ''.join(c for c in country_name if c.isalnum() or c.isspace())  # Remove special chars
            
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
            
            await ctx.send(embed=embed)
        except Exception as e:
            if "Rate limit exceeded" in str(e):
                await ctx.send("잠시 후 다시 시도해주세요. (API 호출 제한)")
            else:
                await ctx.send("해당 국가를 찾을 수 없습니다. 영어로 국가명을 입력해주세요.")
                print(f"Population Error: {e}")

    @population.error
    async def population_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"명령어를 너무 자주 사용하셨습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("국가 이름을 입력해주세요. (예: !!인구 South Korea)")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore command not found errors
        
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"명령어를 너무 자주 사용하셨습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"필요한 인자가 누락되었습니다. 명령어 사용법을 확인해주세요.")
        else:
            await ctx.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
            print(f"Unexpected error: {error}") 