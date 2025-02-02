import logging
from typing import Dict, List

from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)

# Define supported currencies
SUPPORTED_CURRENCIES: List[str] = [
    "USD",
    "EUR",
    "JPY",
    "CNY",
    "GBP",
    "AUD",
    "CAD",
    "HKD",
    "SGD",
    "TWD",
]

# API URL
API_URL = "https://open.er-api.com/v6/latest/KRW"


class ExchangeAPI(BaseAPI):
    def __init__(self):
        """Initialize Exchange API client"""
        super().__init__()
        self._rate_limits = {
            "exchange": RateLimitConfig(60, 60),  # 60 requests per minute
        }

    async def initialize(self) -> None:
        """Initialize Exchange API resources"""
        pass

    async def validate_credentials(self) -> bool:
        """No API key needed for this service"""
        try:
            await self.get_exchange_rates()
            return True
        except Exception as e:
            logger.error(f"Exchange API validation failed: {e}")
            return False

    async def get_exchange_rates(self) -> Dict[str, float]:
        """Get exchange rates for KRW to various currencies

        Returns:
            Dict[str, float]: Exchange rates where key is currency code and value is KRW rate

        Raises:
            ValueError: If API response is invalid or rate is zero
        """
        try:
            data = await self._get_with_retry(API_URL, endpoint="exchange")

            if not data or "rates" not in data:
                raise ValueError("Failed to get exchange rates")

            result = {}
            for currency in SUPPORTED_CURRENCIES:
                rate = data["rates"].get(currency)
                if not rate:
                    logger.warning(f"Missing rate for {currency}")
                    continue
                if rate == 0:
                    logger.error(f"Zero rate received for {currency}")
                    continue
                result[currency] = 1 / rate

            if not result:
                raise ValueError("No valid exchange rates found")

            return result

        except ValueError as e:
            raise e  # Re-raise ValueError as is
        except Exception as e:
            raise ValueError(f"Failed to get exchange rates: {e}") from e

    async def close(self):
        """Cleanup resources"""
        await super().close()
