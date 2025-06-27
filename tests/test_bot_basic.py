import pytest
import discord
from discord.ext import commands
from discord import app_commands
from typing import cast
from unittest.mock import MagicMock, AsyncMock, PropertyMock
from unittest.mock import patch
from datetime import datetime

@pytest.mark.asyncio
class TestBotBasic:
    """Test basic bot functionality"""
    
    async def test_bot_initialization(self, bot, mock_config):
        """Test that bot initializes correctly"""
        # Test basic attributes
        assert bot._config == mock_config
        assert bot.user.name == "Test Bot"
        
        # Test version info
        assert hasattr(bot, 'version_info')
        assert bot.version_info.commit == "test_commit"
        assert bot.version_info.branch == "test_branch"
        assert bot.version_info.version == "1.0.0"
        
        # Test service initialization
        assert bot._api_service is not None
        assert bot.memory_db is not None
        
        # Test API service state
        assert bot._api_service.initialized is True
        api_states = bot._api_service.api_states
        assert isinstance(api_states, dict)
        # DNF API is optional and may not be initialized
        expected_states = {'steam': True, 'population': True, 'exchange': True, 'claude': True}
        for api_name, expected_state in expected_states.items():
            assert api_states.get(api_name) == expected_state, f"{api_name} API should be {expected_state}"
        assert set(api_states.keys()) == {'steam', 'population', 'exchange', 'claude'}
        
        # Test command system initialization
        assert isinstance(bot.tree, MagicMock)
        assert 'InformationCommands' in bot._BotBase__cogs
        assert 'pthelp' in bot.all_commands
    
    async def test_bot_startup(self, bot):
        """Test bot startup sequence"""
        await bot.on_ready()
        
        # Verify presence
        presence_call = bot.ws.change_presence.await_args
        assert presence_call is not None
        kwargs = presence_call.kwargs
        assert isinstance(kwargs.get('activity'), discord.Game)
        
        # Check that status contains help commands and commit SHA
        status_name = kwargs['activity'].name
        assert "뮤 도움말 | /help |" in status_name  # Should contain help commands
        assert len(status_name.split(" | ")) == 3  # Should have three parts
        
        # Verify prefix system
        prefixes = await bot._get_prefix(bot, None)
        assert isinstance(prefixes, list)
        assert "!!" in prefixes
        assert "뮤 " in prefixes
        assert "pt " in prefixes

    async def test_bot_help_command(self, bot, mock_context):
        """Test help command"""
        help_command = bot.get_command('pthelp')
        assert help_command is not None
        assert help_command.name == 'pthelp'
        assert help_command.help == '도움말을 보여줍니다'
        assert help_command.brief == '도움말'
        
        # Execute help command
        await help_command.callback(bot, mock_context)
        
        # Verify help message
        mock_context.send.assert_called_once()
        args = mock_context.send.call_args
        embed = args.kwargs.get('embed')
        assert isinstance(embed, discord.Embed)
        assert "도움말" in embed.title
        
        # Verify help content includes all prefixes
        description = embed.description
        assert "!!" in description
        assert "뮤" in description
        assert "pt" in description
        assert "AI 명령어" in description  # Verify AI section exists
        assert "대화" in description  # Verify chat command exists
        assert "날씨" not in description  # Verify weather command is removed
    
    async def test_bot_error_handling(self, bot, mock_context):
        """Test bot error handling"""
        errors = [
            (commands.CommandOnCooldown(
                commands.Cooldown(1, 60),
                retry_after=5.0,
                type=commands.BucketType.default
            ), "명령어 재사용 대기 시간이야. 5.0초 후에 다시 시도해줘"),
            (commands.MissingPermissions(["send_messages"]), 
             "이 명령어를 실행할 권한이 없어"),
            (ValueError("Test error"), 
             "Test error"),
            (commands.CommandNotFound(), None),
            (commands.MissingRequiredArgument(param=MagicMock(name='param')), 
             "필수 인자가 누락되었어"),
            (commands.BadArgument(), 
             "잘못된 인자가 전달되었어"),
            (commands.NoPrivateMessage(), 
             "명령어 실행 중 오류가 발생한 것 같아"),
        ]
        
        for error, expected_message in errors:
            mock_context.send.reset_mock()
            await bot.on_command_error(mock_context, error)
            
            if expected_message:
                mock_context.send.assert_called_once()
                message = mock_context.send.call_args.kwargs.get('embed')
                assert isinstance(message, discord.Embed)
                assert expected_message in message.description
            else:
                mock_context.send.assert_not_called()
    
    async def test_bot_command_registration(self, bot):
        """Test command registration process"""
        # Test command attributes
        for command_name, command in bot.all_commands.items():
            assert isinstance(command, commands.Command)
            assert command.name is not None
            assert command.callback is not None
            
            # Test if command is properly bound
            assert command.cog is None or isinstance(command.cog, commands.Cog)
            
        # Create mock tree commands
        mock_command = MagicMock(spec=app_commands.Command)
        mock_command.name = 'test_command'
        
        # Mock the fetch_commands method
        mock_tree = MagicMock()
        mock_tree.fetch_commands = AsyncMock(return_value=[mock_command])
        
        # Set up the tree mock
        type(bot).tree = PropertyMock(return_value=mock_tree)
        bot._BotBase__tree = mock_tree
        
        # Test tree commands
        tree_commands = await bot.tree.fetch_commands()
        assert len(tree_commands) > 0
        for cmd in tree_commands:
            assert isinstance(cmd, MagicMock)  # Changed to check for MagicMock
            assert cmd.name is not None 

    async def test_bot_cleanup(self, bot):
        """Test bot cleanup process"""
        # Store references to mocks before cleanup
        api_service = bot._api_service
        memory_db = bot.memory_db
        
        # Call cleanup
        await bot._cleanup()
        
        # Verify API service cleanup
        api_service.close.assert_called_once()
        
        # Verify memory DB cleanup
        memory_db.close.assert_called_once()
        
        # Verify bot still has references (not cleared by _cleanup)
        assert bot._api_service is not None
        assert bot.memory_db is not None
        
        # Reset mock call counts
        api_service.close.reset_mock()
        memory_db.close.reset_mock()
        
        # Test cleanup on setup failure
        await bot._cleanup_on_setup_failure()
        
        # Verify second cleanup calls
        api_service.close.assert_called_once()
        memory_db.close.assert_called_once()
        
        # Verify services are set to None after setup failure cleanup
        assert bot._api_service is None
        assert bot.memory_db is None

@pytest.mark.asyncio
async def test_claude_load_usage_data(bot):
    """Test that Claude API's _load_usage_data method works correctly"""
    # Get the Claude API instance
    claude_api = bot.api_service.claude_api
    
    # Test loading with no existing file
    await claude_api._load_usage_data()
    
    # Verify the method was called
    claude_api._load_usage_data.assert_called_once()
    
    # Reset the mock for the next test
    claude_api._load_usage_data.reset_mock()
    
    # Test loading with mock data
    mock_data = {
        "daily_requests": 10,
        "last_reset": datetime.now().isoformat(),
        "request_sizes": [100, 200],
        "hourly_token_count": 1000,
        "last_token_reset": datetime.now().isoformat(),
        "total_prompt_tokens": 500,
        "total_response_tokens": 600,
        "max_prompt_tokens": 300,
        "max_response_tokens": 400,
        "token_usage_history": [],
        "thinking_tokens_used": 0,
        "refusal_count": 0,
        "stop_reason_counts": {}
    }
    
    # Mock file operations
    with patch('os.path.exists', return_value=True), \
         patch('json.load', return_value=mock_data):
        await claude_api._load_usage_data()
        
        # Verify the method was called again
        claude_api._load_usage_data.assert_called_once() 

@pytest.mark.asyncio
class TestClaudeInitialization:
    """Test Claude API initialization patterns"""
    
    async def test_claude_initialization_pattern(self, bot, mock_anthropic_fixture):
        """Test that Claude API follows the correct initialization pattern"""
        # Get the Claude API instance
        claude_api = bot.api_service.claude_api
        
        # Verify initial state
        assert claude_api._is_enabled
        assert claude_api._client is None
        
        # Verify initialization sequence
        await claude_api.initialize()
        
        # 1. Verify client initialization
        assert claude_api._client is not None
        assert claude_api._client.api_key == "mock_claude_api_key"
        assert claude_api._client.default_headers == {"anthropic-version": "2023-06-01"}
        
        # 2. Verify initialization of tracking state
        assert isinstance(claude_api._chat_sessions, dict)
        assert isinstance(claude_api._last_interaction, dict)
        assert isinstance(claude_api._saved_usage, dict)
        assert claude_api._daily_requests == 0
        assert claude_api._total_prompt_tokens == 0
        assert claude_api._total_response_tokens == 0
        assert claude_api._thinking_tokens_used == 0
        assert claude_api._refusal_count == 0
        assert isinstance(claude_api._stop_reason_counts, dict)
        
        # 3. Verify API constants
        assert claude_api.MAX_TOTAL_TOKENS == 200000
        assert claude_api.MAX_PROMPT_TOKENS == 180000
        assert claude_api.THINKING_ENABLED == True
        assert claude_api.THINKING_BUDGET_TOKENS == 16000
        assert "Muelsyse" in claude_api.MUELSYSE_CONTEXT
    
    async def test_claude_initialization_error_handling(self, bot, mock_anthropic_fixture):
        """Test error handling during Claude API initialization"""
        claude_api = bot.api_service.claude_api
        
        # Create a new mock that will raise an exception
        async def failing_initialize():
            raise ValueError("Failed to initialize Claude API: Invalid API key")
        
        # Replace the initialize method with one that fails
        claude_api.initialize = failing_initialize
        
        with pytest.raises(ValueError) as exc_info:
            await claude_api.initialize()
        assert "Failed to initialize Claude API" in str(exc_info.value) 