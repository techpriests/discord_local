import asyncio
import logging
from typing import Dict

from src.services.api.exchange import ExchangeAPI
from src.services.api.population import PopulationAPI
from src.services.api.steam import SteamAPI
from src.services.api.weather import WeatherAPI

logger = logging.getLogger(__name__)


class APIService:
    """Service for managing various API clients"""

    def __init__(self, config: Dict[str, str]):
        """Initialize API service with configuration

        Args:
            config: Dictionary containing API keys and settings

        Raises:
            ValueError: If required API keys are missing
        """
        try:
            self._steam_api = SteamAPI(self._get_required_key(config, "STEAM_API_KEY"))
            # Make weather API optional
            weather_api_key = config.get("WEATHER_API_KEY", "")
            self._weather_api = WeatherAPI(weather_api_key) if weather_api_key else None
            self._population_api = PopulationAPI()
            self._exchange_api = ExchangeAPI()
        except KeyError as e:
            raise ValueError(f"Missing required API key: {e}") from e
        except Exception as e:
            logger.error(f"Failed to initialize API service: {e}")
            raise ValueError("API 서비스 초기화에 실패했습니다") from e

    def _get_required_key(self, config: Dict[str, str], key: str) -> str:
        """Get required key from config

        Args:
            config: Configuration dictionary
            key: Key to retrieve

        Returns:
            str: Value for the key

        Raises:
            KeyError: If key is missing or empty
        """
        value = config.get(key)
        if not value:
            raise KeyError(f"{key} is required")
        return value

    @property
    def steam(self) -> SteamAPI:
        """Get Steam API client
        
        Returns:
            SteamAPI: Steam API client
        """
        return self._steam_api

    @property
    def weather(self) -> WeatherAPI:
        """Get weather API client
        
        Returns:
            WeatherAPI: Weather API client
            
        Raises:
            ValueError: If weather API is not initialized
        """
        if not self._weather_api:
            raise ValueError("Weather API is not available - API key not provided")
        return self._weather_api

    async def initialize(self) -> None:
        """Initialize all API clients

        Raises:
            ValueError: If any API client fails to initialize
        """
        try:
            await self._steam_api.initialize()
            if self._weather_api:
                await self._weather_api.initialize()
            await self._population_api.initialize()
            await self._exchange_api.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize APIs: {e}")
            raise ValueError("API 초기화에 실패했습니다") from e

    async def validate_credentials(self) -> bool:
        """Validate all API credentials

        Returns:
            bool: True if all credentials are valid
        """
        try:
            apis_to_validate = [
                self._steam_api.validate_credentials(),
                self._population_api.validate_credentials(),
                self._exchange_api.validate_credentials(),
            ]
            
            # Only validate weather API if it's initialized
            if self._weather_api:
                apis_to_validate.append(self._weather_api.validate_credentials())

            results = await asyncio.gather(*apis_to_validate, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    api_names = ["Steam", "Population", "Exchange"]
                    if self._weather_api:
                        api_names.insert(1, "Weather")
                    logger.error(f"{api_names[i]} API validation failed: {result}")
                    return False
                if not result:
                    return False

            return True

        except Exception as e:
            logger.error(f"Error during API validation: {e}")
            return False

    async def close(self) -> None:
        """Cleanup all API clients"""
        try:
            await asyncio.gather(
                self._steam_api.close(),
                self._weather_api.close(),
                self._population_api.close(),
                self._exchange_api.close(),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"Error during API cleanup: {e}")
