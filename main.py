import discord, random
import os
import steam_web_api
import aiohttp
from discord.ext import commands
from fuzzywuzzy import fuzz
from config import TOKEN, STEAM_KEY  # Import tokens from config file

bot = commands.Bot(command_prefix="!!", intents=discord.Intents.all())

# 로그인
@bot.event
async def on_ready():
    print(f"{bot.user.name} 로그인 성공")
    await bot.change_presence(status=discord.Status.online, activity=discord.Game('LIVE'))
    
# 인사
@bot.command(name="안녕", help="인사말", aliases=["인사", "하이"])
async def hello(ctx):
  hi = random.randrange(1,4)
  if hi == 1:
    await ctx.channel.send("안녕하세요")
  elif hi == 2:
    await ctx.channel.send("안녕")
  elif hi == 3:
    await ctx.channel.send("네, 안녕하세요")

# 선택
@bot.command(name="투표", help="여러 선택지 중 하나를 골라드립니다", aliases=["choice", "골라줘"])
async def choose(ctx, *args):
    if len(args) < 2:
        await ctx.send("최소 두 가지 이상의 선택지를 입력해주세요. (예시: !!투표 피자 치킨 햄버거)")
        return
        
    chosen = random.choice(args)
    await ctx.send(f"음... 저는 '{chosen}'을(를) 선택합니다!")

# Close the bot
@bot.command(aliases=["quit"])
@commands.has_permissions(administrator=True)
async def close(ctx):
    await bot.close()
    print("Bot Closed")  # This is optional, but it is there to tell you.
# Steam player count command
@bot.command(name="스팀", help="스팀 게임의 현재 플레이어 수를 알려드립니다")
async def steam_players(ctx, *, game_name):
    try:
        async with aiohttp.ClientSession() as session:
            # Get Steam app list
            async with session.get("https://api.steampowered.com/ISteamApps/GetAppList/v2/") as response:
                data = await response.json()
                apps = data['applist']['apps']
                
                # Find games with similar names using fuzzy matching
                matches = []
                for app in apps:
                    ratio = fuzz.ratio(app['name'].lower(), game_name.lower())
                    if ratio > 80:  # Threshold for similarity (80%)
                        matches.append((app, ratio))
                
                # Sort matches by similarity ratio
                matches.sort(key=lambda x: x[1], reverse=True)
                
                if matches:
                    game = matches[0][0]  # Get the best match
                    
                    # Get player count
                    app_id = game['appid']
                    async with session.get(f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={app_id}") as player_response:
                        player_data = await player_response.json()
                        player_count = player_data['response']['player_count']
                        
                        # Create embed with game info
                        embed = discord.Embed(
                            title=game['name'],
                            url=f"https://store.steampowered.com/app/{app_id}",
                            color=discord.Color.blue()
                        )
                        embed.add_field(name="현재 플레이어 수", value=f"{player_count:,}명")
                        
                        # If the name doesn't exactly match, add a note
                        if game['name'].lower() != game_name.lower():
                            embed.add_field(
                                name="참고", 
                                value=f"입력하신 '{game_name}'와(과) 가장 유사한 게임을 찾았습니다.", 
                                inline=False
                            )
                            
                        embed.set_thumbnail(url=f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg")
                        
                        await ctx.send(embed=embed)
                else:
                    await ctx.send("게임을 찾을 수 없습니다. 다른 검색어로 시도해주세요.")
                    
    except Exception as e:
        await ctx.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
        print(f"Error: {e}")

# Population command
@bot.command(name="인구", help="국가의 인구수를 알려드립니다", aliases=["population"])
async def population(ctx, *, country_name):
    try:
        async with aiohttp.ClientSession() as session:
            # Use name to search for country
            url = f"https://restcountries.com/v3.1/name/{country_name}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    country = data[0]  # Get first match
                    
                    # Extract information
                    official_name = country['name']['official']
                    population = country['population']
                    capital = country.get('capital', ['정보없음'])[0]
                    region = country.get('region', '정보없음')
                    
                    # Format population with commas
                    formatted_population = f"{population:,}"
                    
                    # Create embed
                    embed = discord.Embed(
                        title=f"🌏 {official_name}",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="인구", value=f"{formatted_population}명", inline=False)
                    embed.add_field(name="수도", value=capital, inline=True)
                    embed.add_field(name="지역", value=region, inline=True)
                    
                    # Add flag if available
                    if 'flags' in country and 'png' in country['flags']:
                        embed.set_thumbnail(url=country['flags']['png'])
                    
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("해당 국가를 찾을 수 없습니다. 영어로 국가명을 입력해주세요.")
                    
    except Exception as e:
        await ctx.send("오류가 발생했습니다. 나중에 다시 시도해주세요.")
        print(f"Population Error: {e}")

# Dice rolling command
@bot.command(name="주사위", help="주사위를 굴립니다. (예: !!주사위 또는 !!주사위 20 또는 !!주사위 6 3)", aliases=["roll", "굴려"])
async def roll_dice(ctx, sides: int = 6, times: int = 1):
    try:
        if sides < 2:
            await ctx.send("주사위는 최소 2면 이상이어야 합니다!")
            return
        if times < 1 or times > 10:
            await ctx.send("주사위는 1회부터 10회까지만 굴릴 수 있습니다!")
            return
            
        # Create embed
        embed = discord.Embed(
            title="🎲 주사위 결과",
            color=discord.Color.blue()
        )
        
        if times == 1:
            result = random.randint(1, sides)
            embed.add_field(name=f"D{sides} 결과", value=str(result), inline=False)
        else:
            results = [random.randint(1, sides) for _ in range(times)]
            results_str = ", ".join(map(str, results))
            total = sum(results)
            embed.add_field(name=f"D{sides} {times}회 결과", value=results_str, inline=False)
            embed.add_field(name="합계", value=str(total), inline=False)
            
        await ctx.send(embed=embed)
        
    except ValueError:
        await ctx.send("올바른 숫자를 입력해주세요!")
    except Exception as e:
        await ctx.send("오류가 발생했습니다.")
        print(f"Dice Error: {e}")

# Copy message command
@bot.command(name="따라해", help="메시지를 따라합니다", aliases=["copy", "mimic"])
async def copy_message(ctx, *, message):
    try:
        # Delete the original message
        await ctx.message.delete()
        
        # Send the copied message
        await ctx.send(message)
        
    except discord.Forbidden:
        await ctx.send("메시지를 삭제할 권한이 없습니다.")
    except Exception as e:
        await ctx.send("오류가 발생했습니다.")
        print(f"Copy Error: {e}")

# Ping command
@bot.command(name="핑", help="봇의 지연시간을 확인합니다", aliases=["ping", "레이턴시"])
async def ping(ctx):
    try:
        # Create embed
        embed = discord.Embed(
            title="🏓 퐁!",
            color=discord.Color.green()
        )
        
        # Get latency in milliseconds
        latency = round(bot.latency * 1000)  # Convert to ms
        
        # Add latency info
        embed.add_field(
            name="지연시간", 
            value=f"{latency}ms",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send("오류가 발생했습니다.")
        print(f"Ping Error: {e}")

# 봇 작동
bot.run(TOKEN)  # Use imported TOKEN