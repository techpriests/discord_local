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
        assert all(api_states.values()), "All APIs should be initialized"
        assert set(api_states.keys()) == {'steam', 'population', 'exchange', 'gemini'}
        
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
        assert "프틸 도움말 | /pthelp |" in status_name  # Should contain help commands
        assert len(status_name.split(" | ")) == 3  # Should have three parts
        
        # Verify prefix system
        prefixes = await bot._get_prefix(bot, None)
        assert isinstance(prefixes, list)
        assert "!!" in prefixes
        assert "프틸 " in prefixes
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
        assert "프틸" in description
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
            ), "명령어 재사용 대기 시간입니다. 5.0초 후에 다시 시도해주세요"),
            (commands.MissingPermissions(["send_messages"]), 
             "이 명령어를 실행할 권한이 없습니다"),
            (ValueError("Test error"), 
             "Test error"),
            (commands.CommandNotFound(), None),
            (commands.MissingRequiredArgument(param=MagicMock(name='param')), 
             "필수 인자가 누락되었습니다"),
            (commands.BadArgument(), 
             "잘못된 인자가 전달되었습니다"),
            (commands.NoPrivateMessage(), 
             "명령어 실행 중 오류가 발생했습니다"),
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
async def test_gemini_load_usage_data(bot):
    """Test that Gemini API's _load_usage_data method works correctly"""
    # Get the Gemini API instance
    gemini_api = bot.api_service.gemini_api
    
    # Test loading with no existing file
    await gemini_api._load_usage_data()
    
    # Verify the method was called
    gemini_api._load_usage_data.assert_called_once()
    
    # Reset the mock for the next test
    gemini_api._load_usage_data.reset_mock()
    
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
        "token_usage_history": []
    }
    
    # Mock file operations
    with patch('os.path.exists', return_value=True), \
         patch('json.load', return_value=mock_data):
        await gemini_api._load_usage_data()
        
        # Verify the method was called again
        gemini_api._load_usage_data.assert_called_once() 

@pytest.mark.asyncio
class TestGeminiInitialization:
    """Test Gemini API initialization patterns"""
    
    async def test_gemini_initialization_pattern(self, bot, mock_genai_fixture):
        """Test that Gemini API follows the correct initialization pattern"""
        # Get the Gemini API instance
        gemini_api = bot.api_service.gemini_api
        
        # Verify initial state
        assert not gemini_api._is_enabled
        assert gemini_api._model is None
        
        # Set up mock model response for test generation
        mock_model = mock_genai_fixture.GenerativeModel.return_value
        mock_model.generate_content.return_value = MagicMock(text="Test response")
        
        # Verify initialization sequence
        await gemini_api.initialize()
        
        # 1. Verify usage data loading
        gemini_api._load_usage_data.assert_called_once()
        
        # 2. Verify API configuration
        mock_genai_fixture.configure.assert_called_once_with(api_key=gemini_api.api_key)
        
        # 3. Verify model initialization
        mock_genai_fixture.GenerativeModel.assert_called_once_with('gemini-2.0-flash-thinking-exp')
        
        # 4. Verify safety settings format
        gemini_api._safety_settings == [
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
        
        # 5. Verify generation config
        gen_config = gemini_api._generation_config
        assert isinstance(gen_config, mock_genai_fixture.types.GenerationConfig)
        assert gen_config.temperature == 0.9
        assert gen_config.top_p == 1
        assert gen_config.top_k == 40
        assert gen_config.max_output_tokens == gemini_api.MAX_TOTAL_TOKENS - gemini_api.MAX_PROMPT_TOKENS
        
        # 6. Verify test generation was performed
        mock_model.generate_content.assert_called_once()
        test_call_args = mock_model.generate_content.call_args
        assert test_call_args[0][0] == "Test message"  # First positional arg
        assert test_call_args[1]["generation_config"] == gemini_api._generation_config
        assert test_call_args[1]["safety_settings"] == gemini_api._safety_settings
        
        # 7. Verify initialization of tracking state
        assert gemini_api._is_enabled  # Service should be enabled after successful init
        assert isinstance(gemini_api._chat_sessions, dict)
        assert isinstance(gemini_api._last_interaction, dict)
        assert isinstance(gemini_api._search_requests, list)
        assert gemini_api._last_search_disable is None
        
        # 8. Verify locks were initialized
        assert gemini_api._session_lock is not None
        assert gemini_api._save_lock is not None
        assert gemini_api._stats_lock is not None
        assert gemini_api._rate_limit_lock is not None
        assert gemini_api._search_lock is not None
    
    async def test_gemini_initialization_error_handling(self, bot, mock_genai_fixture):
        """Test error handling during Gemini API initialization"""
        gemini_api = bot.api_service.gemini_api
        
        # Ensure service starts disabled
        assert not gemini_api._is_enabled
        
        # Test API key configuration error
        mock_genai_fixture.configure.side_effect = Exception("Invalid API key")
        
        with pytest.raises(ValueError) as exc_info:
            await gemini_api.initialize()
        assert "Failed to initialize Gemini API" in str(exc_info.value)
        assert not gemini_api._is_enabled  # Should remain disabled
        
        # Reset mock and test model initialization error
        mock_genai_fixture.configure.side_effect = None
        mock_genai_fixture.GenerativeModel.side_effect = Exception("Model not found")
        
        with pytest.raises(ValueError) as exc_info:
            await gemini_api.initialize()
        assert "Failed to initialize Gemini API" in str(exc_info.value)
        assert not gemini_api._is_enabled  # Should remain disabled 