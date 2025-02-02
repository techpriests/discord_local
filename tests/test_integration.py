import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_api_error_handling(bot, interaction, api_service):
    """Test handling of API errors"""
    # Simulate API error
    api_service.steam.find_game.side_effect = Exception("API Error")
    bot.commands.info.steam.callback.side_effect = Exception("API Error")
    
    # Test error handling
    await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    
    # Verify error response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "오류가 발생했습니다" in kwargs['content']

@pytest.mark.asyncio
async def test_rate_limiting(bot, interaction, api_service):
    """Test API rate limiting"""
    # Simulate rate limit
    api_service.steam.find_game.side_effect = ValueError("Rate limit exceeded")
    bot.commands.info.steam.callback.side_effect = ValueError("Rate limit exceeded")
    
    # Test rate limit handling
    await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    
    # Verify rate limit response
    interaction.response.send_message.assert_called_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "잠시 후" in kwargs['content']

@pytest.mark.asyncio
async def test_command_interaction(bot, interaction):
    """Test command interaction flow"""
    # Test deferred response
    interaction.response.is_done.return_value = True
    
    # Mock long-running command
    bot.commands.info.steam.callback.return_value = "Delayed response"
    
    # Test command
    await bot.commands.info.steam.callback(bot.commands.info, interaction, "Test Game")
    
    # Verify followup was used
    interaction.followup.send.assert_called_once() 