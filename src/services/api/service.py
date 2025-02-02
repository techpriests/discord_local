import logging
from typing import Optional

from .exchange import ExchangeAPI
from .population import PopulationAPI
from .steam import SteamAPI
from .weather import WeatherAPI

logger = logging.getLogger(__name__)


class APIService:
    """Service class that manages all API clients."""

    def __init__(self, steam_key: str, weather_key: str):
        """Initialize API service with required API keys

        Args:
            steam_key: Steam API key
            weather_key: OpenWeather API key
        """
        self._steam: Optional[SteamAPI] = None
        self._weather: Optional[WeatherAPI] = None
        self._population: Optional[PopulationAPI] = None
        self._exchange: Optional[ExchangeAPI] = None

        self._steam_key = steam_key
        self._weather_key = weather_key

    @property
    def steam(self) -> Optional[SteamAPI]:
        """Get Steam API client."""
        return self._steam

    @property
    def weather(self) -> Optional[WeatherAPI]:
        """Get Weather API client."""
        return self._weather

    @property
    def population(self) -> Optional[PopulationAPI]:
        """Get Population API client."""
        return self._population

    @property
    def exchange(self) -> Optional[ExchangeAPI]:
        """Get Exchange API client."""
        return self._exchange

    async def initialize(self) -> None:
        """Initialize all API clients

        Raises:
            Exception: If initialization of any API client fails
        """
        try:
            # Initialize Steam API
            self._steam = SteamAPI(self._steam_key)
            await self._steam.initialize()

            # Initialize Weather API
            self._weather = WeatherAPI(self._weather_key)
            await self._weather.initialize()

            # Initialize Population API
            self._population = PopulationAPI()
            await self._population.initialize()

            # Initialize Exchange API
            self._exchange = ExchangeAPI()
            await self._exchange.initialize()

        except Exception as e:
            logger.error(f"Failed to initialize API services: {e}")
            await self.close()  # Cleanup on failure
            raise

    async def close(self) -> None:
        """Cleanup all API resources"""
        apis = [self._steam, self._weather, self._population, self._exchange]
        for api in apis:
            if api:
                try:
                    await api.close()
                except Exception as e:
                    logger.error(f"Error closing {api.__class__.__name__}: {e}")

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
