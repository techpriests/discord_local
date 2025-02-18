from src.bot import DiscordBot
from src.commands.entertainment import EntertainmentCommands
from src.commands.information import InformationCommands
from src.commands.system import SystemCommands
from src.services.api.service import APIService
import os
import asyncio

async def main():
    # Initialize configuration
    config = {
        "STEAM_API_KEY": os.getenv("STEAM_API_KEY"),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY")
    }
    
    # Initialize bot (API service will be initialized in setup_hook)
    bot = DiscordBot(config)
    
    try:
        # Run bot
        await bot.start(os.getenv("DISCORD_TOKEN"))
    except KeyboardInterrupt:
        await bot.close()
    except Exception as e:
        print(f"Error: {e}")
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())