import logging
from typing import Dict, Any, Optional, cast

from .base import BaseAPI, RateLimitConfig
from src.utils.api_types import WeatherInfo

logger = logging.getLogger(__name__)

# API URL
API_URL = "http://api.openweathermap.org/data/2.5/weather"


class WeatherAPI(BaseAPI[WeatherInfo]):
    """OpenWeather API client implementation"""

    WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

    def __init__(self, api_key: str) -> None:
        """Initialize Weather API client"""
        super().__init__(api_key)
        self._api_key = api_key  # Store API key directly
        self._base_params = {
            'appid': api_key,
            'units': 'metric',
            'lang': 'kr'
        }
        self._rate_limits = {
            "weather": RateLimitConfig(60, 60),  # 60 requests per minute
        }

    async def initialize(self) -> None:
        """Initialize Weather API resources"""
        await super().initialize()

    async def validate_credentials(self) -> bool:
        """Validate Weather API key
        
        Returns:
            bool: True if credentials are valid
        """
        try:
            await self.get_weather("Seoul")
            return True
        except Exception as e:
            logger.error(f"Weather API key validation failed: {e}")
            return False

    async def get_weather(self, city: str) -> WeatherInfo:
        """Get weather information for a city
        
        Args:
            city: City name to get weather for

        Returns:
            WeatherInfo: Weather information

        Raises:
            ValueError: If city not found or API error
        """
        try:
            params = {
                **self._base_params,
                'q': city
            }

            data = await self._make_request(
                self.WEATHER_URL,
                params=params,
                endpoint="weather"
            )

            if not isinstance(data, dict):
                raise ValueError("Invalid response format")

            # Validate required fields
            if not all(key in data for key in ['main', 'weather', 'name']):
                raise ValueError("Missing required fields in response")

            # Validate main data
            main_data = data['main']
            if not all(key in main_data for key in ['temp', 'feels_like', 'humidity']):
                raise ValueError("Missing required weather data")

            # Validate weather description
            weather_data = data['weather']
            if not weather_data or not isinstance(weather_data, list):
                raise ValueError("Invalid weather description data")

            return WeatherInfo(
                main=cast(Dict[str, float], data['main']),
                weather=data['weather'],
                name=data['name']
            )

        except ValueError as e:
            logger.error(f"Weather API error for city {city}: {e}")
            raise ValueError(f"날씨 정보를 가져오는데 실패했습니다: {city}") from e
        except Exception as e:
            logger.error(f"Unexpected error getting weather for {city}: {e}")
            raise ValueError(f"날씨 정보를 가져오는데 실패했습니다: {city}") from e

    def _validate_city_name(self, city: str) -> None:
        """Validate city name
        
        Args:
            city: City name to validate

        Raises:
            ValueError: If city name is invalid
        """
        if not city or not isinstance(city, str):
            raise ValueError("City name must be a non-empty string")
        
        if len(city) > 100:
            raise ValueError("City name is too long")
        
        # Remove any dangerous characters
        safe_city = "".join(c for c in city if c.isalnum() or c.isspace())
        if safe_city != city:
            raise ValueError("City name contains invalid characters")

    def _format_weather_data(self, data: Dict[str, Any]) -> WeatherInfo:
        """Format raw weather data into WeatherInfo
        
        Args:
            data: Raw weather data from API

        Returns:
            WeatherInfo: Formatted weather information

        Raises:
            ValueError: If data format is invalid
        """
        try:
            return WeatherInfo(
                main={
                    'temp': float(data['main']['temp']),
                    'feels_like': float(data['main']['feels_like']),
                    'humidity': float(data['main']['humidity'])
                },
                weather=[{
                    'description': w.get('description', '알 수 없음')
                } for w in data['weather']],
                name=str(data['name'])
            )
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Invalid weather data format: {e}") from e

    async def close(self) -> None:
        """Cleanup resources"""
        await super().close()
