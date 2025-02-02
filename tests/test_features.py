import pytest
import discord
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_steam_command(bot, interaction):
    """Test Steam game info command functionality"""
    # Mock embed
    embed = discord.Embed(title="Test Game", description="현재 플레이어: 1,000명")
    bot.commands.info.steam.callback.return_value = embed
    
    # Test command
    await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    
    # Verify response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert isinstance(kwargs.get('embed'), discord.Embed)
    assert "Test Game" in kwargs['embed'].title

@pytest.mark.asyncio
async def test_population_command(bot, interaction):
    """Test population info command functionality"""
    # Mock embed
    embed = discord.Embed(title="Republic of Korea", description="인구: 51,780,579명")
    bot.commands.info.population.callback.return_value = embed
    
    # Test command
    await bot.commands.info.population.callback(bot.commands.info, interaction, "South Korea")
    
    # Verify response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert isinstance(kwargs.get('embed'), discord.Embed)
    assert "Republic of Korea" in kwargs['embed'].title

@pytest.mark.asyncio
async def test_dice_roll(bot, interaction):
    """Test dice rolling functionality"""
    # Mock response
    bot.commands.entertainment.roll.callback.return_value = "🎲 주사위 결과: 7"
    
    # Test command
    await bot.commands.entertainment.roll.callback(bot.commands.entertainment, interaction, "2d6")
    
    # Verify response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "🎲" in kwargs['content']
    assert "주사위" in kwargs['content'] 