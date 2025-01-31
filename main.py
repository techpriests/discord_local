from src.bot import DiscordBot
from src.commands.entertainment import EntertainmentCommands
from src.commands.information import InformationCommands
from src.commands.system import SystemCommands
from src.services.api import APIService
from config import TOKEN, WEATHER_API_KEY, STEAM_KEY

def main():
    # Initialize services
    api_service = APIService(WEATHER_API_KEY, STEAM_KEY)
    
    # Initialize bot
    bot = DiscordBot()
    
    # Load cogs
    bot.load_cogs([
        EntertainmentCommands(),
        InformationCommands(api_service),
        SystemCommands(bot.bot)
    ])
    
    # Run bot
    bot.run(TOKEN)

if __name__ == "__main__":
    main()