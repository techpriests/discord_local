import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from discord.ext import commands
from src.bot import DiscordBot
from src.services.api.service import APIService

@pytest.fixture
async def bot():
    """Create a bot instance for testing"""
    bot = DiscordBot()
    
    # Mock essential bot attributes
    mock_user = MagicMock(spec=discord.ClientUser)
    mock_user.name = "Test Bot"
    mock_user.id = 123456789
    
    # Mock bot's internal state
    mock_state = MagicMock()
    mock_state.user = mock_user
    mock_connection = MagicMock()
    mock_connection._get_state.return_value = mock_state
    
    # Set up bot's internal state
    bot.bot._connection = mock_connection
    
    # Mock command tree
    bot.bot.tree = MagicMock()
    bot.bot.tree.sync = AsyncMock()
    bot.bot.tree.get_commands = MagicMock(return_value=[])
    
    # Mock command methods
    bot.commands = MagicMock()
    bot.commands.info = MagicMock()
    bot.commands.entertainment = MagicMock()
    bot.commands.system = MagicMock()
    
    # Mock command callbacks
    steam_cmd = AsyncMock()
    steam_cmd.callback = AsyncMock()
    bot.commands.info.steam = steam_cmd
    
    pop_cmd = AsyncMock()
    pop_cmd.callback = AsyncMock()
    bot.commands.info.population = pop_cmd
    
    roll_cmd = AsyncMock()
    roll_cmd.callback = AsyncMock()
    bot.commands.entertainment.roll = roll_cmd
    
    # Mock error handler
    bot.bot.on_command_error = AsyncMock()
    
    return bot

@pytest.fixture
def interaction():
    """Create a Discord interaction for testing"""
    interaction = MagicMock(spec=discord.Interaction)
    
    # Mock response
    response = MagicMock()
    response.send_message = AsyncMock()
    response.defer = AsyncMock()
    response.is_done = MagicMock(return_value=False)
    interaction.response = response
    
    # Mock followup
    followup = MagicMock()
    followup.send = AsyncMock()
    interaction.followup = followup
    
    return interaction

@pytest.fixture
def api_service():
    """Create API service with mocked endpoints"""
    service = MagicMock(spec=APIService)
    
    # Mock Steam API
    steam = MagicMock()
    steam.find_game = AsyncMock(return_value=({
        'name': 'Test Game',
        'player_count': 1000
    }, 100, None))
    service.steam = steam
    
    # Mock Population API
    population = MagicMock()
    population.get_country_info = AsyncMock(return_value={
        'name': {'official': 'Republic of Korea'},
        'population': 51780579,
        'capital': ['Seoul']
    })
    service.population = population
    
    return service 