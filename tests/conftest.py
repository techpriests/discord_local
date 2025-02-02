import pytest
from typing import AsyncGenerator, Dict, Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch, PropertyMock
from contextlib import ExitStack

import discord
from discord.ext import commands
from discord import app_commands  # Import app_commands directly

from src.bot import DiscordBot
from src.services.api_service import APIService
from src.commands.base_commands import BaseCommands

@pytest.fixture
def mock_config() -> Dict[str, str]:
    """Create mock config dictionary with proper API keys"""
    return {
        "DISCORD_TOKEN": "test_token",
        "WEATHER_API_KEY": "test_weather_key",
        "STEAM_API_KEY": "test_steam_key"
    }

@pytest.fixture
def mock_api_service() -> MagicMock:
    """Create mock API service with all required methods"""
    service = MagicMock(spec=APIService)
    service.initialize = AsyncMock()
    service.steam = MagicMock()
    service.weather = MagicMock()
    service.population = MagicMock()
    service.exchange = MagicMock()
    return service

@pytest.fixture
def mock_command_tree() -> MagicMock:
    """Create mock command tree"""
    tree = MagicMock()
    tree.sync = AsyncMock()
    return tree

@pytest.fixture
async def bot(mock_config, mock_api_service, mock_command_tree) -> AsyncGenerator[DiscordBot, None]:
    """Create test bot instance with all required mocks and attributes"""
    # Create mock user and websocket
    mock_user = MagicMock(spec=discord.ClientUser)
    mock_user.name = "Test Bot"
    
    mock_ws = AsyncMock()
    mock_ws.change_presence = AsyncMock()
    
    # Create mock client
    mock_client = MagicMock(spec=discord.Client)
    mock_client.ws = mock_ws
    mock_client.user = mock_user
    
    # Set up patches
    patches = [
        patch('discord.ext.commands.Bot.__init__', return_value=None),
        patch('discord.app_commands.CommandTree', return_value=mock_command_tree),
        patch('discord.Client', return_value=mock_client),
        patch('src.bot.APIService', return_value=mock_api_service),
    ]
    
    # Apply patches and create bot
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        
        bot = DiscordBot(mock_config)
        
        # Set up internal bot state
        bot._connection = MagicMock()
        bot._connection.user = mock_user
        bot.ws = mock_ws
        bot._closing_task = None
        
        # Set up command system (using internal names)
        bot._BotBase__cogs = {}
        bot._BotBase__extensions = {}
        bot._BotBase__commands = {}
        bot._BotBase__listeners = {}
        bot._BotBase__help_command = None
        bot._BotBase__tree = mock_command_tree
        bot.all_commands = {}
        
        # Initialize services
        bot._api_service = mock_api_service
        bot.memory_db = MagicMock()
        
        # Create a mock help command function if help_prefix doesn't exist
        async def mock_help_command(self, ctx):
            embed = discord.Embed(title="도움말", description="명령어")
            await ctx.send(embed=embed)
        
        # Add command registration - Fixed command creation
        help_command = commands.Command(
            mock_help_command,
            name='help',
            help='도움말을 보여줍니다.',
            brief='도움말'
        )
        bot.all_commands['help'] = help_command
        bot._BotBase__commands['help'] = help_command
        
        # Add activity for presence
        bot.activity = discord.Game(name="!!help | /help")
        
        # Mock tree commands for command registration test
        mock_app_command = MagicMock(spec=app_commands.Command)
        mock_app_command.name = 'test_command'
        
        mock_command_tree.fetch_commands = AsyncMock(return_value=[
            mock_app_command
        ])
        
        yield bot
        
        # Cleanup
        try:
            await bot.close()
        except Exception:
            pass

@pytest.fixture
def mock_interaction() -> discord.Interaction:
    """Create mock interaction with all required attributes"""
    interaction = create_autospec(discord.Interaction)
    
    # Response handling
    interaction.response = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    
    # Followup handling
    interaction.followup = AsyncMock()
    interaction.followup.send = AsyncMock()
    
    # User info
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.name = "Test User"
    interaction.user.id = 123
    
    # Guild info
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 789
    
    return interaction

@pytest.fixture
def mock_context() -> commands.Context:
    """Create mock context with all required attributes"""
    ctx = create_autospec(commands.Context)
    
    # Message handling
    ctx.send = AsyncMock()
    ctx.message = MagicMock(spec=discord.Message)
    ctx.message.delete = AsyncMock()
    
    # Channel info
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.id = 123
    
    # Author info
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.name = "Test User"
    ctx.author.id = 456
    
    # Guild info
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.guild.id = 789
    
    # Command info
    ctx.command = MagicMock(spec=commands.Command)
    ctx.command.name = "test_command"
    
    return ctx 