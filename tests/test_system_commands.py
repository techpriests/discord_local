import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from src.commands.system import SystemCommands

@pytest.fixture
def bot():
    bot = MagicMock(spec=discord.Bot)
    bot.latency = 0.1
    return bot

@pytest.fixture
def system_commands(bot):
    return SystemCommands(bot)

@pytest.mark.asyncio
async def test_ping():
    # Setup
    bot = MagicMock(spec=discord.Bot)
    bot.latency = 0.1
    commands = SystemCommands(bot)
    
    # Mock context
    ctx = MagicMock()
    ctx.send = AsyncMock()
    
    # Test ping
    await commands._handle_ping(ctx)
    assert ctx.send.called 