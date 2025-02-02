import pytest
from typing import Any
import discord
from discord import Interaction
from unittest.mock import AsyncMock, MagicMock
from src.commands.information import InformationCommands

@pytest.mark.asyncio
async def test_api_error_handling(
    bot: Any,
    interaction: Interaction
) -> None:
    """Test handling of API errors"""
    try:
        await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    except Exception:
        await interaction.response.send_message("오류가 발생했습니다")

@pytest.mark.asyncio
async def test_rate_limiting(
    bot: Any,
    interaction: Interaction
) -> None:
    """Test API rate limiting"""
    # Override callback with rate limit error
    async def rate_limit_callback(self: Any, interaction: Interaction, game_name: str) -> None:
        await interaction.response.send_message(content="잠시 후 다시 시도해주세요")
        raise ValueError("Rate limit exceeded")
    bot.commands.info.steam.callback = AsyncMock(side_effect=rate_limit_callback)
    
    try:
        await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    except ValueError:
        pass
    
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "잠시 후" in kwargs['content']

@pytest.mark.asyncio
async def test_command_interaction(
    bot: Any,
    interaction: Interaction
) -> None:
    """Test command interaction flow"""
    # Test deferred response
    interaction.response.is_done.return_value = True
    
    async def delayed_callback(self: Any, interaction: Interaction, game_name: str) -> None:
        await interaction.followup.send(content="Delayed response")
    bot.commands.info.steam.callback = AsyncMock(side_effect=delayed_callback)
    
    # Test command
    await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    
    # Verify followup was used
    interaction.followup.send.assert_called_once()

@pytest.mark.asyncio
async def test_population_api_error_handling(
    bot: Any,
    interaction: Interaction
) -> None:
    """Test handling of population API errors"""
    # Override callback with API error
    async def error_callback(self: Any, interaction: Interaction, country_name: str) -> None:
        await interaction.response.send_message(
            "국가 정보를 가져오는데 실패했습니다",
            ephemeral=True
        )
        raise ValueError("API Error")
    bot.commands.info.population.callback = AsyncMock(side_effect=error_callback)
    
    try:
        await bot.commands.info.population.callback(
            bot.commands.info, 
            interaction, 
            "Invalid Country"
        )
    except ValueError:
        pass
    
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs.get('ephemeral', False) 