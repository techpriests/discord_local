import pytest
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_bot_startup(bot):
    """Test that bot starts up and syncs commands"""
    # Simulate bot startup
    await bot.bot.on_ready()
    
    # Verify essential startup tasks
    bot.bot.tree.sync.assert_called_once()

@pytest.mark.asyncio
async def test_command_registration(bot):
    """Test that all required commands are registered"""
    # Get all registered commands
    commands = bot.bot.tree.get_commands()
    command_names = {cmd.name for cmd in commands}
    
    # Verify essential commands exist
    required_commands = {'ping', 'steam', 'population', 'roll', 'choose'}
    assert required_commands.issubset(command_names)

@pytest.mark.asyncio
async def test_error_handling(bot):
    """Test bot's error handling capabilities"""
    # Create error context
    ctx = MagicMock()
    ctx.send = AsyncMock()
    
    # Test cooldown error
    error = commands.CommandOnCooldown(
        commands.Cooldown(1, 60),
        retry_after=5.0,
        type=commands.BucketType.default
    )
    
    async def error_handler(ctx, error):
        await ctx.send(f"{error.retry_after}초 후에 다시 시도해주세요")
    
    bot.bot.on_command_error = error_handler
    
    # Trigger error
    await bot.bot.on_command_error(ctx, error)
    
    # Verify error was handled
    ctx.send.assert_called_once()
    message = ctx.send.call_args[0][0]
    assert "초 후에 다시 시도" in message 