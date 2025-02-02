import pytest
from typing import Any, Dict
import discord
from discord import Interaction, Embed
from discord.ext.commands import Context
from unittest.mock import AsyncMock, MagicMock
from src.commands.information import InformationCommands
from src.commands.entertainment import EntertainmentCommands

@pytest.mark.asyncio
async def test_steam_command(
    bot: Any,
    interaction: Interaction
) -> None:
    """Test Steam game info command functionality"""
    # Test command
    await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    
    # Verify response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert isinstance(kwargs.get('embed'), Embed)
    assert "Test Game" in kwargs['embed'].title

@pytest.mark.asyncio
async def test_population_command(
    bot: Any,
    interaction: Interaction,
    mock_country_data: Dict[str, Any]
) -> None:
    """Test population info command functionality"""
    # Test command
    await bot.commands.info.population.callback(bot.commands.info, interaction, "South Korea")
    
    # Verify response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert isinstance(kwargs.get('embed'), Embed)
    assert "Republic of Korea" in kwargs['embed'].title
    assert "51,780,579명" in str(kwargs['embed'].fields[0].value)

@pytest.mark.asyncio
async def test_dice_roll(
    bot: Any,
    interaction: Interaction
) -> None:
    """Test dice rolling functionality"""
    # Test command
    await bot.commands.entertainment.roll.callback(bot.commands.entertainment, interaction, "2d6")
    
    # Verify response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "🎲" in kwargs['content']
    assert "주사위" in kwargs['content'] 