import logging
from typing import Dict, TypedDict

from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)

# API URL
API_URL = "http://api.openweathermap.org/data/2.5/weather"


class WeatherInfo(TypedDict):
    """Type definition for weather information"""

    main: Dict[str, float]  # Contains temp, feels_like, humidity
    weather: list[Dict[str, str]]  # Contains description


class WeatherAPI(BaseAPI):
    """OpenWeather API client implementation."""

    def __init__(self, api_key: str):
        """Initialize Weather API client.
        
        Args:
            api_key: OpenWeather API key
        """
        super().__init__()
        self._api_key = api_key
        self._rate_limits = {
            "weather": RateLimitConfig(60, 60),  # 60 requests per minute
        }

    @property
    def api_key(self) -> str:
        """Get the API key"""
        return self._api_key

    async def initialize(self) -> None:
        """Initialize Weather API resources"""
        pass

    async def validate_credentials(self) -> bool:
        """Validate Weather API key"""
        try:
            await self.get_weather("Seoul")
            return True
        except Exception as e:
            logger.error(f"Weather API key validation failed: {e}")
            return False

    async def get_weather(self, city: str) -> WeatherInfo:
        """Get weather information for a city

        Args:
            city: Name of the city to get weather for

        Returns:
            WeatherInfo: Dictionary containing weather information

        Raises:
            ValueError: If city not found or invalid response
            Exception: If API request fails
        """
        try:
            params = {"q": city, "appid": self.api_key, "units": "metric", "lang": "kr"}
            return await self._get_with_retry(API_URL, params, "weather")
        except Exception as e:
            raise ValueError(f"Failed to get weather data: {e}") from e

    async def close(self):
        """Cleanup resources"""
        await super().close()
