import asyncio
import logging
from typing import Dict

from .api.exchange import ExchangeAPI
from .api.population import PopulationAPI
from .api.steam import SteamAPI
from .api.weather import WeatherAPI

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
            self._weather_api = WeatherAPI(self._get_required_key(config, "WEATHER_API_KEY"))
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

    async def initialize(self) -> None:
        """Initialize all API clients

        Raises:
            ValueError: If any API client fails to initialize
        """
        try:
            await self._steam_api.initialize()
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
            results = await asyncio.gather(
                self._steam_api.validate_credentials(),
                self._weather_api.validate_credentials(),
                self._population_api.validate_credentials(),
                self._exchange_api.validate_credentials(),
                return_exceptions=True,
            )

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    api_names = ["Steam", "Weather", "Population", "Exchange"]
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
