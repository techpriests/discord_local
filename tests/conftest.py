import pytest
from typing import AsyncGenerator, Dict, Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch, PropertyMock
from contextlib import ExitStack
import os
import sys
import asyncio
import google.genai as genai  # Import the real package first

# Set up mocks before any imports
class MockHarmCategory:
    """Mock HarmCategory enum"""
    HARM_CATEGORY_HARASSMENT = "HARM_CATEGORY_HARASSMENT"
    HARM_CATEGORY_HATE_SPEECH = "HARM_CATEGORY_HATE_SPEECH"
    HARM_CATEGORY_SEXUALLY_EXPLICIT = "HARM_CATEGORY_SEXUALLY_EXPLICIT"
    HARM_CATEGORY_DANGEROUS_CONTENT = "HARM_CATEGORY_DANGEROUS_CONTENT"

class MockHarmBlockThreshold:
    BLOCK_NONE = "BLOCK_NONE"

class MockGenerationConfig:
    def __init__(self, temperature=None, top_p=None, top_k=None, max_output_tokens=None):
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.max_output_tokens = max_output_tokens

# Create mock for genai module while preserving the real types
mock_genai = MagicMock(wraps=genai)  # Wrap the real module
mock_genai.types = MagicMock()
mock_genai.types.HarmCategory = MockHarmCategory
mock_genai.types.HarmBlockThreshold = MockHarmBlockThreshold
mock_genai.types.GenerationConfig = MockGenerationConfig
mock_genai.types.HttpOptions = MagicMock(return_value=MagicMock())
mock_genai.Client = MagicMock()
mock_genai.configure = MagicMock()
mock_genai.GenerativeModel = MagicMock()

mock_model = MagicMock()
mock_model.generate_content = MagicMock(return_value=MagicMock(text="Test response"))
mock_model.count_tokens = MagicMock(return_value=MagicMock(total_tokens=10))
mock_model.aio.chats.create = MagicMock(return_value=MagicMock())
mock_genai.GenerativeModel.return_value = mock_model

# Mock psutil module
mock_psutil = MagicMock()
mock_psutil.cpu_percent.return_value = 50.0
mock_psutil.virtual_memory.return_value = MagicMock(percent=60.0)
sys.modules['psutil'] = mock_psutil

# Now we can import the rest
import discord
from discord.ext import commands
from discord import app_commands

from src.bot import DiscordBot
from src.services.api.service import APIService
from src.commands.base_commands import BaseCommands

@pytest.fixture
def mock_config() -> Dict[str, str]:
    """Create mock config dictionary with proper API keys"""
    return {
        "DISCORD_TOKEN": "mock_discord_token",
        "STEAM_API_KEY": "mock_steam_api_key",
        "GEMINI_API_KEY": "mock_gemini_api_key",
    }

@pytest.fixture(autouse=True)
def mock_genai_fixture():
    """Mock google.generativeai module"""
    return mock_genai

@pytest.fixture
def mock_api_service(mock_genai_fixture) -> MagicMock:
    """Create mock API service with all required methods"""
    service = MagicMock(spec=APIService)
    service.initialize = AsyncMock()
    service.steam = MagicMock()
    service.population = MagicMock()
    service.exchange = MagicMock()
    
    # Create a proper mock for Gemini API
    gemini = MagicMock()
    
    # Set initial state using property mock to ensure proper behavior
    enabled_prop = PropertyMock(return_value=False)
    type(gemini)._is_enabled = enabled_prop
    gemini._model = None  # Start with no model
    gemini.api_key = "mock_gemini_api_key"
    
    # Mock initialize to actually call configure and set up the model
    async def mock_initialize():
        try:
            # Load usage data first
            await gemini._load_usage_data()
            
            # Configure API
            mock_genai_fixture.configure(api_key=gemini.api_key)
            mock_genai_fixture.http_options = MagicMock()
            mock_genai_fixture.types.HttpOptions = MagicMock(return_value=MagicMock())
            
            # Get model
            gemini._model = mock_genai_fixture.GenerativeModel(
                model_name='gemini-2.5-pro-preview-03-25'
            )
            
            # Initialize locks
            gemini._session_lock = AsyncMock()
            gemini._save_lock = AsyncMock()
            gemini._stats_lock = AsyncMock()
            gemini._rate_limit_lock = AsyncMock()
            gemini._search_lock = AsyncMock()
            
            # Initialize tracking state
            gemini._chat_sessions = {}
            gemini._last_interaction = {}
            gemini._search_requests = []
            gemini._last_search_disable = None
            
            # Test generation
            await asyncio.sleep(0)  # Simulate async operation
            gemini._model.generate_content(
                "Test message",
                generation_config=gemini._generation_config,
                safety_settings=gemini._safety_settings
            )
            
            enabled_prop.return_value = True  # Update the property mock
            return True
            
        except Exception as e:
            enabled_prop.return_value = False  # Update the property mock
            raise ValueError(f"Failed to initialize Gemini API: {str(e)}")
    
    gemini.initialize = AsyncMock(side_effect=mock_initialize)
    gemini.chat = AsyncMock()
    gemini._load_usage_data = AsyncMock()
    gemini._saved_usage = {}
    
    # Add required attributes for test verification
    gemini._safety_settings = [
        {
            "category": mock_genai_fixture.types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            "threshold": mock_genai_fixture.types.HarmBlockThreshold.BLOCK_NONE
        },
        {
            "category": mock_genai_fixture.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            "threshold": mock_genai_fixture.types.HarmBlockThreshold.BLOCK_NONE
        },
        {
            "category": mock_genai_fixture.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            "threshold": mock_genai_fixture.types.HarmBlockThreshold.BLOCK_NONE
        },
        {
            "category": mock_genai_fixture.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            "threshold": mock_genai_fixture.types.HarmBlockThreshold.BLOCK_NONE
        }
    ]
    
    gemini._generation_config = mock_genai_fixture.types.GenerationConfig(
        temperature=0.9,
        top_p=1,
        top_k=40,
        max_output_tokens=24000  # MAX_TOTAL_TOKENS (32000) - MAX_PROMPT_TOKENS (8000)
    )
    
    gemini.MAX_TOTAL_TOKENS = 32000
    gemini.MAX_PROMPT_TOKENS = 8000
    
    # Set up the property mock for gemini_api
    gemini_api = PropertyMock(return_value=gemini)
    type(service).gemini_api = gemini_api
    service.gemini = gemini
    
    service.validate_credentials = AsyncMock(return_value=True)
    
    # Add new API state tracking
    service.api_states = {
        'steam': True,
        'population': True,
        'exchange': True,
        'gemini': True
    }
    service.initialized = True
    service._cleanup_apis = AsyncMock()
    service.close = AsyncMock()
    
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
        patch('discord.Client', return_value=mock_client),
        patch('src.bot.APIService', return_value=mock_api_service),
    ]
    
    # Apply patches and create bot
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        
        # Set up version info environment variables
        os.environ["GIT_COMMIT"] = "test_commit"
        os.environ["GIT_BRANCH"] = "test_branch"
        
        # Create bot with proper initialization
        intents = discord.Intents.default()
        intents.message_content = True
        bot = DiscordBot(mock_config)
        commands.Bot.__init__(bot, command_prefix=["!!", "프틸 ", "pt "], intents=intents)
        
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
        bot.extra_events = {}  # Initialize extra_events dictionary
        
        # Initialize services
        bot._api_service = mock_api_service
        memory_db = MagicMock()
        memory_db.close = AsyncMock()  # Make close an async mock
        memory_db.store = AsyncMock()  # Add store method
        memory_db.recall = AsyncMock(return_value={})  # Add recall method
        memory_db.forget = AsyncMock(return_value=True)  # Add forget method
        bot.memory_db = memory_db
        
        # Set up command prefix
        bot.command_prefix = ["!!", "프틸 ", "pt "]
        
        # Create a mock help command function
        async def mock_help_command(self, ctx):
            embed = discord.Embed(
                title="도움말",
                description=(
                    "명령어 사용법:\n"
                    "• !!명령어 - 기본 접두사\n"
                    "• 프틸 명령어 - 한글 접두사\n"
                    "• pt command - 영문 접두사\n\n"
                    "AI 명령어:\n"
                    "• 대화 - Gemini AI와 대화하기"
                )
            )
            await ctx.send(embed=embed)
        
        # Add command registration
        help_command = commands.Command(
            mock_help_command,
            name='pthelp',
            help='도움말을 보여줍니다',
            brief='도움말'
        )
        bot.all_commands['pthelp'] = help_command
        bot._BotBase__commands['pthelp'] = help_command
        
        # Register ping command for prefix tests
        async def ping_command(self, ctx):
            await ctx.send("Pong!")
        
        ping = commands.Command(
            ping_command,
            name='핑',
            help='핑퐁 테스트',
            brief='핑퐁',
            aliases=['ping']
        )
        bot.all_commands['핑'] = ping
        bot.all_commands['ping'] = ping
        bot._BotBase__commands['핑'] = ping
        
        # Register information commands
        from src.commands.information import InformationCommands
        info_cog = InformationCommands(mock_api_service)
        await bot.add_cog(info_cog)
        
        # Register all commands from the cog
        for cmd in info_cog.get_commands():
            cmd.cog = info_cog  # Ensure cog is properly set
            bot.all_commands[cmd.name] = cmd
            if hasattr(cmd, 'aliases'):
                for alias in cmd.aliases:
                    bot.all_commands[alias] = cmd
        
        # Update test expectations
        bot._BotBase__cogs = {'InformationCommands': info_cog}
        
        # Add activity for presence
        bot.activity = discord.Game(name="!!help | /help")
        
        # Mock tree commands for command registration test
        mock_app_command = MagicMock(spec=app_commands.Command)
        mock_app_command.name = 'test_command'
        
        mock_command_tree.fetch_commands = AsyncMock(return_value=[
            mock_app_command
        ])
        
        # Register all commands from the cog
        for cmd in info_cog.get_commands():
            bot.all_commands[cmd.name] = cmd
            bot._BotBase__commands[cmd.name] = cmd
            if hasattr(cmd, 'aliases'):
                for alias in cmd.aliases:
                    bot.all_commands[alias] = cmd
                    bot._BotBase__commands[alias] = cmd
        
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