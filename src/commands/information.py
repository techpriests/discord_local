from discord.ext import commands
import discord
from ..services.api import APIService

class InformationCommands(commands.Cog):
    def __init__(self, api_service: APIService):
        self.api = api_service
    
    @commands.command(name="날씨", help="서울의 현재 날씨를 알려드립니다", aliases=["weather"])
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
            await ctx.send("날씨 정보를 가져오는데 실패했습니다.")
            print(f"Weather Error: {e}")
    
    @commands.command(name="스팀", help="스팀 게임의 현재 플레이어 수를 알려드립니다")
    async def steam(self, ctx, *, game_name: str):
        try:
            game, similarity = await self.api.find_game(game_name)
            if not game:
                await ctx.send("게임을 찾을 수 없습니다.")
                return
            
            player_count = await self.api.get_player_count(game['appid'])
            
            embed = discord.Embed(
                title=game['name'],
                url=f"https://store.steampowered.com/app/{game['appid']}",
                color=discord.Color.blue()
            )
            embed.add_field(name="현재 플레이어 수", value=f"{player_count:,}명")
            
            if similarity < 100:
                embed.add_field(
                    name="참고", 
                    value=f"입력하신 '{game_name}'와(과) 가장 유사한 게임을 찾았습니다.",
                    inline=False
                )
            
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("오류가 발생했습니다.")
            print(f"Steam Error: {e}")
    
    @commands.command(name="인구", help="국가의 인구수를 알려드립니다", aliases=["population"])
    async def population(self, ctx, *, country_name: str):
        try:
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
            await ctx.send("해당 국가를 찾을 수 없습니다. 영어로 국가명을 입력해주세요.")
            print(f"Population Error: {e}") 