from src.bot import DiscordBot
from src.commands.entertainment import EntertainmentCommands
from src.commands.information import InformationCommands
from src.commands.system import SystemCommands
from src.services.api import APIService
from src.services.secrets import SecretsManager
import asyncio

async def main():
    # Get secrets from AWS
    secrets_manager = SecretsManager("discord_bot_secrets")  # Create this secret in AWS
    secrets = secrets_manager.get_secrets()
    
    # Initialize services with secrets
    api_service = APIService(
        weather_key=secrets['WEATHER_API_KEY'],
        steam_key=secrets['STEAM_KEY']
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
        
        # Run bot with token from secrets
        await bot.start(secrets['TOKEN'])
    except KeyboardInterrupt:
        await api_service.close()
    except Exception as e:
        print(f"Error: {e}")
        await api_service.close()

if __name__ == "__main__":
    asyncio.run(main())