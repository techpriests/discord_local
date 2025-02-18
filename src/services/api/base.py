import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List, Optional, TypeVar, Generic, cast

import aiohttp
from src.utils.types import JsonDict

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RateLimitConfig:
    """Configuration for API rate limiting

    Attributes:
        requests (int): Number of requests allowed in the period
        period (int): Time period in seconds
        backoff_factor (float): Multiplier for exponential backoff
    """

    def __init__(self, requests: int, period: int, backoff_factor: float = 1.5) -> None:
        if requests <= 0 or period <= 0 or backoff_factor <= 1:
            raise ValueError("Invalid rate limit configuration")
        self.requests = requests
        self.period = period
        self.backoff_factor = backoff_factor


class BaseAPI(ABC, Generic[T]):
    """Base class for API clients"""
    
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._logger = logging.getLogger(self.__class__.__name__)
        self._rate_limits: Dict[str, RateLimitConfig] = {}
        self._request_timestamps: Dict[str, List[float]] = {}
        self._backoff_times: Dict[str, float] = {}

    @property
    def session(self) -> Optional[aiohttp.ClientSession]:
        """Get current aiohttp session."""
        return self._session

    @property
    def backoff_times(self) -> Dict[str, float]:
        """Get current backoff times for endpoints."""
        return self._backoff_times.copy()

    def get_rate_limit(self, endpoint: str) -> Optional[RateLimitConfig]:
        """Get rate limit config for endpoint."""
        return self._rate_limits.get(endpoint)

    def get_request_timestamps(self, endpoint: str) -> List[float]:
        """Get request timestamps for endpoint."""
        return self._request_timestamps[endpoint].copy()

    async def initialize(self) -> None:
        """Initialize API client"""
        try:
            if self._session:
                if not self._session.closed:
                    return  # Session already initialized and active
                else:
                    await self._session.close()  # Clean up closed session
                    self._session = None
            
            # Create new session
            self._session = aiohttp.ClientSession()
            logger.debug(f"{self.__class__.__name__} session initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize {self.__class__.__name__} session: {e}")
            if self._session:
                await self._session.close()
                self._session = None
            raise ValueError(f"Failed to initialize API session: {str(e)}") from e

    async def close(self) -> None:
        """Close API client"""
        if self._session:
            try:
                if not self._session.closed:
                    await self._session.close()
            except Exception as e:
                logger.error(f"Error closing {self.__class__.__name__} session: {e}")
            finally:
                self._session = None

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Validate API credentials
        
        Returns:
            bool: True if credentials are valid
        """
        pass

    async def _make_request(
        self, 
        url: str, 
        method: str = "GET", 
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        endpoint: Optional[str] = None,
        custom_request: Optional[callable] = None
    ) -> JsonDict:
        """Make HTTP request
        
        Args:
            url: Request URL
            method: HTTP method
            params: Query parameters
            headers: Request headers
            endpoint: API endpoint for rate limiting
            custom_request: Optional callable for custom request handling

        Returns:
            JsonDict: Response data

        Raises:
            ValueError: If request fails
        """
        if not self._session and not custom_request:
            raise ValueError("API client not initialized")

        if endpoint:
            await self._check_rate_limit(endpoint)

        try:
            if custom_request:
                response = await custom_request()
                if endpoint:
                    self._record_request(endpoint)
                return response

            async with self._session.request(
                method, 
                url, 
                params=params, 
                headers=headers
            ) as response:
                if response.status != 200:
                    raise ValueError(f"API request failed: {response.status}")
                    
                data = await response.json()
                if endpoint:
                    self._record_request(endpoint)
                return cast(JsonDict, data)

        except aiohttp.ClientError as e:
            self._logger.error(f"API request failed: {e}")
            raise ValueError("API 요청에 실패했습니다") from e

    async def _check_rate_limit(self, endpoint: str) -> None:
        """Check and enforce rate limits
        
        Args:
            endpoint: API endpoint to check
            
        Raises:
            ValueError: If rate limit exceeded
        """
        if endpoint not in self._rate_limits:
            return

        config = self._rate_limits[endpoint]
        current_time = time.time()
        
        # Initialize timestamps if needed
        if endpoint not in self._request_timestamps:
            self._request_timestamps[endpoint] = []
            
        # Remove old timestamps
        self._request_timestamps[endpoint] = [
            ts for ts in self._request_timestamps[endpoint]
            if current_time - ts <= config.period
        ]
        
        # Check rate limit
        if len(self._request_timestamps[endpoint]) >= config.requests:
            wait_time = self._calculate_wait_time(endpoint, current_time, config)
            raise ValueError(f"Rate limit exceeded. Please wait {wait_time:.1f} seconds.")

    def _record_request(self, endpoint: str) -> None:
        """Record API request timestamp
        
        Args:
            endpoint: API endpoint to record
        """
        current_time = time.time()
        if endpoint not in self._request_timestamps:
            self._request_timestamps[endpoint] = []
        self._request_timestamps[endpoint].append(current_time)

    def _calculate_wait_time(
        self, 
        endpoint: str, 
        current_time: float, 
        config: RateLimitConfig
    ) -> float:
        """Calculate wait time for rate limit
        
        Args:
            endpoint: API endpoint
            current_time: Current timestamp
            config: Rate limit configuration

        Returns:
            float: Time to wait in seconds
        """
        oldest_request = min(self._request_timestamps[endpoint])
        return oldest_request + config.period - current_time

    async def __aenter__(self) -> 'BaseAPI[T]':
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit"""
        await self.close()
