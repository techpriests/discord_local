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
    
    # Create a completely mocked bot
    mock_bot = MagicMock()
    mock_bot._connection = mock_connection
    mock_bot.user = mock_user
    
    # Mock command tree
    mock_tree = MagicMock()
    mock_tree.sync = AsyncMock()
    mock_tree.get_commands = MagicMock(return_value=[
        MockCommand("ping"),
        MockCommand("steam"),
        MockCommand("population"),
        MockCommand("roll"),
        MockCommand("choose")
    ])
    mock_bot.tree = mock_tree
    
    # Set up event handlers
    async def ready_handler():
        await mock_bot.tree.sync()
    mock_bot.on_ready = ready_handler
    mock_bot.on_command_error = AsyncMock()
    
    # Replace the internal bot instance
    bot.bot = mock_bot
    
    # Mock command groups
    bot.commands = MagicMock()
    bot.commands.info = MagicMock()
    bot.commands.entertainment = MagicMock()
    bot.commands.system = MagicMock()
    
    # Mock specific commands
    steam_cmd = AsyncMock()
    async def steam_callback(self, interaction, game_name):
        embed = discord.Embed(title="Test Game", description="현재 플레이어: 1,000명")
        await interaction.response.send_message(embed=embed)
    steam_cmd.callback = AsyncMock(side_effect=steam_callback)
    bot.commands.info.steam = steam_cmd
    
    pop_cmd = AsyncMock()
    async def pop_callback(self, interaction, country):
        embed = discord.Embed(title="Republic of Korea")
        embed.add_field(name="인구", value="51,780,579명", inline=False)
        embed.add_field(name="수도", value="Seoul", inline=True)
        embed.add_field(name="지역", value="Asia", inline=True)
        await interaction.response.send_message(embed=embed)
    pop_cmd.callback = AsyncMock(side_effect=pop_callback)
    bot.commands.info.population = pop_cmd
    
    roll_cmd = AsyncMock()
    async def roll_callback(self, interaction, dice):
        await interaction.response.send_message(content="🎲 주사위 결과: 7")
    roll_cmd.callback = AsyncMock(side_effect=roll_callback)
    bot.commands.entertainment.roll = roll_cmd
    
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
def mock_country_data():
    """Create mock country data for testing"""
    return {
        'name': {'official': 'Republic of Korea'},
        'population': 51780579,
        'capital': ['Seoul'],
        'region': 'Asia',
        'flags': {'png': 'http://test.com/flag.png'}
    }

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
    
    # Mock Population API - Update with more complete data
    population = MagicMock()
    population.get_country_info = AsyncMock(return_value=mock_country_data())
    service.population = population
    
    return service

class MockCommand:
    def __init__(self, name):
        self.name = name 