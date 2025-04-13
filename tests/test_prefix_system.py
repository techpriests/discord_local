import pytest
from discord.ext import commands
from unittest.mock import MagicMock, AsyncMock
import discord

@pytest.mark.asyncio
class TestPrefixSystem:
    """Test the bot's prefix system functionality"""

    async def test_prefix_recognition(self, bot, mock_context):
        """Test that bot recognizes all prefixes"""
        prefixes = await bot._get_prefix(bot, mock_context.message)
        assert isinstance(prefixes, list)
        assert "!!" in prefixes
        assert "뮤 " in prefixes  # Note the space
        assert "pt " in prefixes    # Note the space

    async def test_command_with_different_prefixes(self, bot, mock_context):
        """Test commands work with different prefixes"""
        test_messages = [
            ("!!핑", "핑"),
            ("뮤 핑", "핑"),
            ("pt ping", "ping")
        ]

        for msg, cmd in test_messages:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Set up message content
            mock_context.message.content = msg
            mock_context.prefix = msg.split()[0]
            mock_context.invoked_with = cmd
            mock_context.command = bot.get_command(cmd)

            # Process command
            command = bot.get_command(cmd)
            assert command is not None
            assert command.name in ['핑', 'ping']

            # Execute command
            await command(bot, mock_context)

            # Verify response was sent
            mock_context.send.assert_called_once()

    async def test_space_requirement(self, bot, mock_context):
        """Test that 뮤 and pt require a space after them"""
        invalid_messages = [
            "뮤핑",  # No space
            "pt핑",   # No space
        ]

        for msg in invalid_messages:
            # Create a mock message
            mock_message = MagicMock(spec=discord.Message)
            mock_message.content = msg
            
            # Get context
            ctx = await bot.get_context(mock_message)
            assert ctx.valid is False
            assert ctx.command is None

    async def test_case_sensitivity(self, bot, mock_context):
        """Test case sensitivity of prefixes"""
        test_messages = [
            ("PT ping", "ping"),    # Should work (case insensitive)
            ("Pt Ping", "ping"),    # Should work (case insensitive)
            ("뮤 핑", "핑"),     # Should work (no case sensitivity for Korean)
        ]

        for msg, cmd in test_messages:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Set up message content
            mock_context.message.content = msg
            mock_context.prefix = msg.split()[0].lower()  # Bot should convert to lowercase
            mock_context.invoked_with = cmd.lower()  # Bot should convert to lowercase
            mock_context.command = bot.get_command(cmd.lower())

            # Process command
            command = bot.get_command(cmd.lower())
            assert command is not None
            assert command.name in ['핑', 'ping']

            # Execute command
            await command(bot, mock_context)

            # Verify response was sent
            mock_context.send.assert_called_once()

    async def test_alias_system(self, bot, mock_context):
        """Test that aliases work with all prefixes"""
        test_cases = [
            ("!!인구", "인구", ["인구", "population"]),
            ("뮤 인구", "인구", ["인구", "population"]),
            ("pt population", "population", ["인구", "population"]),
            ("!!스팀", "스팀", ["스팀", "steam"]),
            ("뮤 스팀", "스팀", ["스팀", "steam"]),
            ("pt steam", "steam", ["스팀", "steam"]),
        ]

        for msg, cmd, expected_commands in test_cases:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Set up message content
            mock_context.message.content = msg
            mock_context.prefix = msg.split()[0]
            mock_context.invoked_with = cmd
            mock_context.command = bot.get_command(cmd)

            # Check command exists
            command = bot.get_command(cmd)
            assert command is not None
            assert command.name in expected_commands
            assert any(alias in expected_commands for alias in command.aliases)

            # Execute command with proper context
            await command(mock_context)

            # Verify response was sent
            mock_context.send.assert_called_once() 

    async def test_prefix_in_conversation(self, bot, mock_context):
        """Test that prefixes are only recognized at the start of messages"""
        test_messages = [
            "내가 뮤 보내야 할까?",  # 뮤 in middle of Korean sentence
            "I need to pt this exercise",  # pt in middle of English sentence
            "이것은 !!아닙니다",  # !! in middle of Korean word
            "Let's!! do this",  # !! in middle of English sentence
            "뮤스팀",  # 뮤 without space
            "ptping",   # pt without space
        ]

        for msg in test_messages:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Create a mock message
            mock_message = MagicMock(spec=discord.Message)
            mock_message.content = msg
            
            # Get context
            ctx = await bot.get_context(mock_message)
            
            # Verify that no command was detected
            assert ctx.valid is False, f"Message '{msg}' was incorrectly interpreted as a command"
            assert ctx.command is None, f"Message '{msg}' should not trigger any command"
            assert ctx.prefix is None, f"Message '{msg}' should not match any prefix" 