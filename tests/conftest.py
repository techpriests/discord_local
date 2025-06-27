import pytest
from typing import AsyncGenerator, Dict, Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch, PropertyMock
from contextlib import ExitStack
import os
import sys
import asyncio

# Mock anthropic module
class MockAnthropicMessage:
    def __init__(self, content="Test response"):
        self.content = [{"type": "text", "text": content}]
        self.usage = MagicMock()
        self.usage.input_tokens = 10
        self.usage.output_tokens = 5
        self.stop_reason = "end_turn"

class MockAnthropicClient:
    def __init__(self, api_key=None, default_headers=None):
        self.api_key = api_key
        self.default_headers = default_headers
        self.messages = MagicMock()
        self.messages.create = AsyncMock(return_value=MockAnthropicMessage())
        self.messages.count_tokens = AsyncMock(return_value=MagicMock(input_tokens=10))

# Create mock for anthropic module
mock_anthropic = MagicMock()
mock_anthropic.AsyncAnthropic = MockAnthropicClient
sys.modules['anthropic'] = mock_anthropic

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
        "CL_API_KEY": "mock_claude_api_key",
    }

@pytest.fixture(autouse=True)
def mock_anthropic_fixture():
    """Mock anthropic module"""
    return mock_anthropic

@pytest.fixture
def mock_api_service(mock_anthropic_fixture) -> MagicMock:
    """Create mock API service with all required methods"""
    service = MagicMock(spec=APIService)
    service.initialize = AsyncMock()
    service.steam = MagicMock()
    service.population = MagicMock()
    service.exchange = MagicMock()
    
    # Create a proper mock for Claude API
    claude = MagicMock()
    
    # Set initial state
    claude._is_enabled = True
    claude._client = None
    claude.api_key = "mock_claude_api_key"
    
    # Mock initialize to set up the client
    async def mock_initialize():
        try:
            # Initialize the Anthropic client
            claude._client = mock_anthropic_fixture.AsyncAnthropic(
                api_key=claude.api_key,
                default_headers={"anthropic-version": "2023-06-01"}
            )
            
            # Initialize tracking state
            claude._chat_sessions = {}
            claude._last_interaction = {}
            claude._saved_usage = {}
            claude._daily_requests = 0
            claude._total_prompt_tokens = 0
            claude._total_response_tokens = 0
            claude._thinking_tokens_used = 0
            claude._refusal_count = 0
            claude._stop_reason_counts = {
                "end_turn": 0,
                "max_tokens": 0,
                "stop_sequence": 0,
                "tool_use": 0,
                "pause_turn": 0,
                "refusal": 0,
                "unknown": 0
            }
            
            return True
            
        except Exception as e:
            raise ValueError(f"Failed to initialize Claude API: {str(e)}")
    
    claude.initialize = AsyncMock(side_effect=mock_initialize)
    claude.chat = AsyncMock(return_value=("Test response", None))
    claude._load_usage_data = AsyncMock()
    
    # Add required attributes for test verification
    claude.MAX_TOTAL_TOKENS = 200000
    claude.MAX_PROMPT_TOKENS = 180000
    claude.THINKING_ENABLED = True
    claude.THINKING_BUDGET_TOKENS = 16000
    claude.MUELSYSE_CONTEXT = "You are Muelsyse, test context"
    
    # Set up the property mock for claude_api
    claude_api = PropertyMock(return_value=claude)
    type(service).claude_api = claude_api
    service.claude = claude
    
    service.validate_credentials = AsyncMock(return_value=True)
    
    # Add new API state tracking
    service.api_states = {
        'steam': True,
        'population': True,
        'exchange': True,
        'claude': True
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
        commands.Bot.__init__(bot, command_prefix=["!!", "뮤 ", "pt "], intents=intents)
        
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
        bot.command_prefix = ["!!", "뮤 ", "pt "]
        
        # Create a mock help command function
        async def mock_help_command(self, ctx):
            embed = discord.Embed(
                title="도움말",
                description=(
                    "명령어 사용법:\n"
                    "• !!명령어 - 기본 접두사\n"
                    "• 뮤 명령어 - 한글 접두사\n"
                    "• pt command - 영문 접두사\n\n"
                    "AI 명령어:\n"
                    "• 대화 - Claude AI와 대화하기"
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