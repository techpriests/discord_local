import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from src.commands.information import InformationCommands
from src.services.api import APIService

@pytest.fixture
def api_service():
    service = MagicMock(spec=APIService)
    service.get_weather = AsyncMock()
    service.get_country_info = AsyncMock()
    service.find_game = AsyncMock()
    service.get_player_count = AsyncMock()
    return service

@pytest.fixture
def info_commands(api_service):
    return InformationCommands(api_service)

@pytest.mark.asyncio
async def test_weather_command():
    # Mock weather data
    weather_data = {
        'main': {
            'temp': 20,
            'feels_like': 22,
            'humidity': 60
        },
        'weather': [{'description': 'clear sky'}]
    }
    
    # Setup mocks
    api_service = MagicMock(spec=APIService)
    api_service.get_weather = AsyncMock(return_value=weather_data)
    
    # Create command instance
    commands = InformationCommands(api_service)
    
    # Mock context/interaction
    ctx = MagicMock()
    ctx.send = AsyncMock()
    
    # Execute command
    await commands._handle_weather(ctx)
    
    # Verify
    api_service.get_weather.assert_called_once_with("Seoul")
    assert ctx.send.called

@pytest.mark.asyncio
async def test_time_conversion():
    # Setup
    api_service = MagicMock(spec=APIService)
    commands = InformationCommands(api_service)
    
    # Mock context
    ctx = MagicMock()
    ctx.send = AsyncMock()
    
    # Test basic time conversion
    await commands._handle_time(ctx, "US/Pacific")
    assert ctx.send.called 