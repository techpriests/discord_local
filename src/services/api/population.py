import logging
from typing import Dict, TypedDict

from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)


class CountryInfo(TypedDict):
    """Type definition for country information"""

    name: Dict[str, str]  # Contains 'official' and other name variants
    population: int
    capital: list[str]  # List of capital cities


API_URL = "https://restcountries.com/v3.1/name/{}"


class PopulationAPI(BaseAPI):
    def __init__(self):
        """Initialize Population API client"""
        super().__init__()
        self._rate_limits = {
            "country": RateLimitConfig(30, 60),  # 30 requests per minute
        }

    async def initialize(self) -> None:
        """Initialize Population API resources"""
        pass

    async def validate_credentials(self) -> bool:
        """No API key needed for this service"""
        try:
            await self.get_country_info("South Korea")
            return True
        except Exception as e:
            logger.error(f"Population API validation failed: {e}")
            return False

    async def get_country_info(self, country_name: str) -> CountryInfo:
        """Get country information including population data

        Args:
            country_name: Name of the country to look up

        Returns:
            CountryInfo: Dictionary containing country information

        Raises:
            ValueError: If country not found or invalid response
            KeyError: If required fields are missing from response
        """
        url = API_URL.format(country_name)
        data = await self._get_with_retry(url, endpoint="country")

        if not data or not isinstance(data, list) or not data:
            raise ValueError(f"No data found for country: {country_name}")

        try:
            country_data = data[0]
            return {
                "name": country_data["name"],
                "population": country_data["population"],
                "capital": country_data["capital"],
            }
        except KeyError as e:
            logger.error(f"Missing required field in response: {e}")
            raise KeyError(f"Invalid response format: missing {e}") from e

    async def close(self):
        """Cleanup resources"""
        await super().close()
