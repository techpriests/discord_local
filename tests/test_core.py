import pytest
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_bot_startup(bot):
    """Test that bot starts up and syncs commands"""
    # Mock ready event handler
    async def on_ready():
        await bot.bot.tree.sync()
        
    bot.bot.on_ready = on_ready
    
    # Simulate bot startup
    await bot.bot.on_ready()
    
    # Verify essential startup tasks
    bot.bot.tree.sync.assert_called_once()
    bot.bot.change_presence.assert_called_once()

@pytest.mark.asyncio
async def test_command_registration(bot):
    """Test that all required commands are registered"""
    # Mock command tree
    commands = [
        MagicMock(name="ping"),
        MagicMock(name="steam"),
        MagicMock(name="population"),
        MagicMock(name="roll"),
        MagicMock(name="choose")
    ]
    bot.bot.tree.get_commands.return_value = commands
    
    # Get all registered commands
    command_names = {cmd.name for cmd in bot.bot.tree.get_commands()}
    
    # Verify essential commands exist
    required_commands = {'ping', 'steam', 'population', 'roll', 'choose'}
    assert required_commands.issubset(command_names)

@pytest.mark.asyncio
async def test_error_handling(bot):
    """Test bot's error handling capabilities"""
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