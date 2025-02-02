import logging
from typing import Dict, Optional, cast

from src.services.api.steam import SteamAPI
from src.services.api.weather import WeatherAPI
from src.services.api.exchange import ExchangeAPI
from src.services.api.population import PopulationAPI

logger = logging.getLogger(__name__)

class APIService:
    """Service managing all API clients"""

    def __init__(self, config: Dict[str, str]) -> None:
        """Initialize API service
        
        Args:
            config: Dictionary containing API keys
        """
        self._config = config
        self._steam_api: Optional[SteamAPI] = None
        self._weather_api: Optional[WeatherAPI] = None
        self._exchange_api: Optional[ExchangeAPI] = None
        self._population_api: Optional[PopulationAPI] = None

    async def initialize(self) -> None:
        """Initialize all API clients"""
        try:
            # Initialize Steam API
            self._steam_api = SteamAPI(self._config["STEAM_API_KEY"])
            await self._steam_api.initialize()

            # Initialize Weather API
            self._weather_api = WeatherAPI(self._config["WEATHER_API_KEY"])
            await self._weather_api.initialize()

            # Initialize Exchange API
            self._exchange_api = ExchangeAPI()
            await self._exchange_api.initialize()

            # Initialize Population API
            self._population_api = PopulationAPI()
            await self._population_api.initialize()

        except Exception as e:
            await self.close()
            raise ValueError(f"Failed to initialize API services: {e}") from e

    @property
    def exchange(self) -> ExchangeAPI:
        """Get Exchange API client"""
        if not self._exchange_api:
            raise ValueError("Exchange API not initialized")
        return self._exchange_api

    @property
    def steam(self) -> SteamAPI:
        """Get Steam API client"""
        if not self._steam_api:
            raise ValueError("Steam API not initialized")
        return self._steam_api

    @property
    def weather(self) -> WeatherAPI:
        """Get Weather API client"""
        if not self._weather_api:
            raise ValueError("Weather API not initialized")
        return self._weather_api

    @property
    def population(self) -> PopulationAPI:
        """Get Population API client"""
        if not self._population_api:
            raise ValueError("Population API not initialized")
        return self._population_api

    async def close(self) -> None:
        """Close all API clients"""
        apis = [
            self._steam_api,
            self._weather_api,
            self._exchange_api,
            self._population_api
        ]

        for api in apis:
            if api:
                try:
                    await api.close()
                except Exception as e:
                    logger.error(f"Error closing {api.__class__.__name__}: {e}")

        self._steam_api = None
        self._weather_api = None
        self._exchange_api = None
        self._population_api = None

    async def __aenter__(self) -> 'APIService':
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit"""
        await self.close()

    async def get_exchange_rates(self) -> Dict[str, float]:
        """Get current exchange rates"""
        return await self.exchange.get_exchange_rates()
