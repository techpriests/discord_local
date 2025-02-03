from src.bot import DiscordBot
from src.commands.entertainment import EntertainmentCommands
from src.commands.information import InformationCommands
from src.commands.system import SystemCommands
from src.services.api.service import APIService
import os
import asyncio

async def main():
    # Initialize services
    config = {
        "STEAM_API_KEY": os.getenv("STEAM_API_KEY"),
        "WEATHER_API_KEY": os.getenv("WEATHER_API_KEY")
    }
    
    api_service = APIService(config)
    
    # Initialize bot
    bot = DiscordBot(config)
    
    try:
        # Load cogs
        await bot.load_cogs([
            EntertainmentCommands(),
            InformationCommands(api_service),
            SystemCommands(bot.bot)
        ], api_service)
        
        # Run bot
        await bot.start(os.getenv("DISCORD_TOKEN"))
    except KeyboardInterrupt:
        await api_service.close()
    except Exception as e:
        print(f"Error: {e}")
        await api_service.close()

if __name__ == "__main__":
    asyncio.run(main())