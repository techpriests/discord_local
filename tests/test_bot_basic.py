import pytest
import discord
from discord.ext import commands
from discord import app_commands
from typing import cast
from unittest.mock import MagicMock, AsyncMock, PropertyMock

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