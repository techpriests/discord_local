import logging
from typing import Dict, Any, Optional, TypedDict, List

from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)


class CountryInfo(TypedDict):
    """Country information type"""
    name: str
    population: int
    growth_rate: float
    area: float


API_URL = "https://restcountries.com/v3.1/name/{}"


class PopulationAPI(BaseAPI[CountryInfo]):
    """Population API client implementation"""

    COUNTRY_API_URL = "https://restcountries.com/v3.1/name/{}"

    def __init__(self) -> None:
        """Initialize Population API client"""
        super().__init__()
        self._rate_limits = {
            "country": RateLimitConfig(30, 60),  # 30 requests per minute
        }
        self._supported_countries: List[str] = []
        self._cached_data: Optional[Dict[str, CountryInfo]] = None

    async def initialize(self) -> None:
        """Initialize Population API resources"""
        await super().initialize()

    async def validate_credentials(self) -> bool:
        """Validate API access (no credentials needed)"""
        try:
            await self.get_country_info("South Korea")
            return True
        except Exception:
            return False

    async def get_country_info(self, country_name: str) -> CountryInfo:
        """Get country information
        
        Args:
            country_name: Name of country to look up

        Returns:
            CountryInfo: Country information

        Raises:
            ValueError: If country not found or API error
        """
        url = self.COUNTRY_API_URL.format(country_name)
        data = await self._make_request(url)
        
        if not data or not isinstance(data, list):
            raise ValueError(f"국가를 찾을 수 없습니다: {country_name}")
            
        country_data = data[0]
        return CountryInfo(
            name=country_data['name']['common'],
            population=country_data['population'],
            growth_rate=country_data['population_growth'],
            area=country_data['area']
        )

    async def close(self) -> None:
        """Cleanup resources"""
        await super().close()
