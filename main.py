from src.bot import DiscordBot
from src.commands.entertainment import EntertainmentCommands
from src.commands.information import InformationCommands
from src.commands.system import SystemCommands
from src.services.api.service import APIService
from config import TOKEN, WEATHER_API_KEY, STEAM_KEY
import asyncio

async def main():
    # Initialize services
    api_service = APIService(
        steam_key=STEAM_KEY,
        weather_key=WEATHER_API_KEY
    )
    
    # Initialize bot
    bot = DiscordBot()
    
    try:
        # Load cogs
        await bot.load_cogs([
            EntertainmentCommands(),
            InformationCommands(api_service),
            SystemCommands(bot.bot)
        ], api_service)
        
        # Run bot
        await bot.start(TOKEN)
    except KeyboardInterrupt:
        await api_service.close()
    except Exception as e:
        print(f"Error: {e}")
        await api_service.close()

if __name__ == "__main__":
    asyncio.run(main())