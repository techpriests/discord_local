import pytest
from unittest.mock import AsyncMock, MagicMock
from src.bot import DiscordBot
from discord.ext import commands

@pytest.fixture
def bot():
    return DiscordBot()

def test_bot_initialization(bot):
    assert bot.bot is not None
    assert isinstance(bot.bot, commands.Bot)

@pytest.mark.asyncio
async def test_load_cogs(bot):
    # Create mock cogs
    mock_cog1 = MagicMock()
    mock_cog2 = MagicMock()
    mock_api_service = MagicMock()
    
    # Test cog loading
    await bot.load_cogs([mock_cog1, mock_cog2], mock_api_service)
    
    # Verify bot has api_service
    assert bot.api_service == mock_api_service

@pytest.mark.asyncio
async def test_on_ready(bot):
    # Mock the bot's methods
    bot.bot.tree.sync = AsyncMock()
    bot.bot.change_presence = AsyncMock()
    
    # Simulate on_ready event
    await bot.bot.on_ready()
    
    # Verify sync and presence change were called
    assert bot.bot.tree.sync.called
    assert bot.bot.change_presence.called
