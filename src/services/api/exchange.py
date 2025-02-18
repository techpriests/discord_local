import logging
from typing import Dict, Optional, List, cast
import asyncio

from .base import BaseAPI, RateLimitConfig
from src.utils.api_types import ExchangeRates

logger = logging.getLogger(__name__)

# Supported currencies
SUPPORTED_CURRENCIES: List[str] = [
    "USD",  # US Dollar
    "EUR",  # Euro
    "JPY",  # Japanese Yen
    "CNY",  # Chinese Yuan
    "GBP",  # British Pound
    "AUD",  # Australian Dollar
    "CAD",  # Canadian Dollar
    "HKD",  # Hong Kong Dollar
    "SGD",  # Singapore Dollar
    "TWD",  # Taiwan Dollar
]

# API URL
API_URL = "https://open.er-api.com/v6/latest/KRW"


class ExchangeAPI(BaseAPI[Dict[str, float]]):
    """Exchange rate API client implementation"""

    EXCHANGE_URL = "https://api.exchangerate-api.com/v4/latest/KRW"

    def __init__(self) -> None:
        """Initialize Exchange API client"""
        super().__init__("")  # Exchange API doesn't need an API key
        self._rate_limits = {
            "exchange": RateLimitConfig(60, 60),  # 60 requests per minute
        }
        self._cached_rates: Optional[Dict[str, float]] = None
        self._supported_currencies = set(SUPPORTED_CURRENCIES)

    async def initialize(self) -> None:
        """Initialize Exchange API resources"""
        try:
            logger.info("Initializing Exchange API...")
            
            # Initialize base class first
            await super().initialize()
            
            if not self._session:
                raise ValueError("Session not initialized")
                
            # Test API access during initialization with retry
            max_retries = 3
            retry_delay = 1.0
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    logger.debug(f"Exchange API initialization attempt {attempt + 1}/{max_retries}")
                    data = await self._make_request(
                        self.EXCHANGE_URL,
                        endpoint="exchange"
                    )
                    
                    if not isinstance(data, dict) or 'rates' not in data:
                        raise ValueError("Invalid API response format")
                    
                    # Cache initial rates
                    self._cached_rates = {
                        curr: rate for curr, rate in data['rates'].items()
                        if curr in self._supported_currencies
                    }
                    
                    if not self._cached_rates:
                        raise ValueError("No supported currencies found in API response")
                    
                    logger.info(f"Exchange API initialized successfully with {len(self._cached_rates)} currencies")
                    return
                    
                except Exception as e:
                    last_error = e
                    if attempt == max_retries - 1:
                        break
                    logger.warning(f"Exchange API initialization attempt {attempt + 1} failed: {str(e)}")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
            
            # If we get here, all retries failed
            error_msg = f"Failed to initialize Exchange API after {max_retries} attempts"
            if last_error:
                error_msg += f": {str(last_error)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        except Exception as e:
            logger.error(f"Exchange API initialization failed: {str(e)}")
            # Clean up session if initialization fails
            await self.close()
            raise ValueError(f"Exchange API initialization failed: {str(e)}") from e

    async def validate_credentials(self) -> bool:
        """Validate API access (no credentials needed)
        
        Returns:
            bool: True if API is accessible
        """
        try:
            # If we have cached rates from initialization, we're already validated
            if self._cached_rates:
                logger.debug("Exchange API validated using cached rates")
                return True
                
            # If we get here, initialization didn't complete successfully
            logger.warning("Exchange API validation called without successful initialization")
            return False
            
        except Exception as e:
            logger.error(f"Exchange API validation failed: {str(e)}")
            return False

    async def get_exchange_rates(self) -> Dict[str, float]:
        """Get current exchange rates
        
        Returns:
            Dict[str, float]: Exchange rates with currency codes as keys

        Raises:
            ValueError: If API request fails or response is invalid
        """
        try:
            data = await self._make_request(
                self.EXCHANGE_URL,
                endpoint="exchange"
            )

            if not isinstance(data, dict) or 'rates' not in data:
                raise ValueError("Invalid response format")

            rates = cast(Dict[str, float], data['rates'])
            
            # Validate rates
            self._validate_rates(rates)
            
            # Filter to supported currencies only
            filtered_rates = self._filter_supported_rates(rates)
            
            # Cache the rates
            self._cached_rates = filtered_rates
            
            return filtered_rates

        except ValueError as e:
            logger.error(f"Exchange API error: {e}")
            if self._cached_rates:
                logger.info("Using cached exchange rates")
                return self._cached_rates
            raise ValueError("환율 정보를 가져오는데 실패했습니다") from e
        except Exception as e:
            logger.error(f"Unexpected error getting exchange rates: {e}")
            if self._cached_rates:
                logger.info("Using cached exchange rates")
                return self._cached_rates
            raise ValueError("환율 정보를 가져오는데 실패했습니다") from e

    def _validate_rates(self, rates: Dict[str, float]) -> None:
        """Validate exchange rates
        
        Args:
            rates: Exchange rates to validate

        Raises:
            ValueError: If rates are invalid
        """
        if not rates:
            raise ValueError("Empty exchange rates")

        for currency, rate in rates.items():
            if not isinstance(currency, str) or len(currency) != 3:
                raise ValueError(f"Invalid currency code: {currency}")
            if not isinstance(rate, (int, float)) or rate <= 0:
                raise ValueError(f"Invalid rate for {currency}: {rate}")

    def _filter_supported_rates(self, rates: Dict[str, float]) -> Dict[str, float]:
        """Filter rates to only include supported currencies
        
        Args:
            rates: All exchange rates

        Returns:
            Dict[str, float]: Filtered exchange rates
        """
        return {
            currency: rate 
            for currency, rate in rates.items()
            if currency in self._supported_currencies
        }

    def get_supported_currencies(self) -> List[str]:
        """Get list of supported currencies
        
        Returns:
            List[str]: List of supported currency codes
        """
        return list(self._supported_currencies)

    def is_currency_supported(self, currency: str) -> bool:
        """Check if currency is supported
        
        Args:
            currency: Currency code to check

        Returns:
            bool: True if currency is supported
        """
        return currency.upper() in self._supported_currencies

    async def close(self) -> None:
        """Cleanup resources"""
        await super().close()
