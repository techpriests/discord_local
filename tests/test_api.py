import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.api import APIService

@pytest.fixture
def api_service():
    return APIService("test_weather_key", "test_steam_key")

@pytest.mark.asyncio
async def test_get_weather():
    with patch('aiohttp.ClientSession.get') as mock_get:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            'main': {'temp': 20, 'feels_like': 22, 'humidity': 60},
            'weather': [{'description': 'clear sky'}]
        })
        mock_get.return_value.__aenter__.return_value = mock_response
        
        # Test API call
        api = APIService("test_weather_key", "test_steam_key")
        weather = await api.get_weather("Seoul")
        
        assert weather['main']['temp'] == 20
        assert 'weather' in weather

@pytest.mark.asyncio
async def test_get_country_info():
    with patch('aiohttp.ClientSession.get') as mock_get:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value=[{
            'name': {'official': 'Republic of Korea'},
            'population': 51780579,
            'capital': ['Seoul'],
            'region': 'Asia'
        }])
        mock_get.return_value.__aenter__.return_value = mock_response
        
        # Test API call
        api = APIService("test_weather_key", "test_steam_key")
        country = await api.get_country_info("South Korea")
        
        assert country['name']['official'] == 'Republic of Korea'
        assert 'population' in country

@pytest.mark.asyncio
async def test_find_game():
    with patch('aiohttp.ClientSession.get') as mock_get:
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            'applist': {
                'apps': [
                    {'appid': 1234, 'name': 'Test Game'}
                ]
            }
        })
        mock_get.return_value.__aenter__.return_value = mock_response
        
        # Test API call
        api = APIService("test_weather_key", "test_steam_key")
        game, similarity, matches = await api.find_game("Test Game")
        
        assert game is not None
        assert game['name'] == 'Test Game'
