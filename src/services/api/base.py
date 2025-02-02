import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class RateLimitConfig:
    """Configuration for API rate limiting

    Attributes:
        requests (int): Number of requests allowed in the period
        period (int): Time period in seconds
        backoff_factor (float): Multiplier for exponential backoff
    """

    def __init__(self, requests: int, period: int, backoff_factor: float = 1.5):
        if requests <= 0:
            raise ValueError("requests must be positive")
        if period <= 0:
            raise ValueError("period must be positive")
        if backoff_factor <= 1:
            raise ValueError("backoff_factor must be greater than 1")

        self._requests = requests
        self._period = period
        self._backoff_factor = backoff_factor

    @property
    def requests(self) -> int:
        """Number of requests allowed in the period"""
        return self._requests

    @property
    def period(self) -> int:
        """Time period in seconds"""
        return self._period

    @property
    def backoff_factor(self) -> float:
        """Multiplier for exponential backoff"""
        return self._backoff_factor


class BaseAPI(ABC):
    """Abstract base class for API clients with rate limiting and error handling."""

    def __init__(self):
        """Initialize API client with session and rate limiting."""
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limits: Dict[str, RateLimitConfig] = {}
        self._backoff_times: Dict[str, float] = {}
        self._request_timestamps: Dict[str, List[float]] = defaultdict(list)

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

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize any required resources"""
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Validate API credentials"""
        pass

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        endpoint: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Base request method with retry logic

        Args:
            url: API endpoint URL
            params: Query parameters
            endpoint: API endpoint name for rate limiting
            max_retries: Maximum number of retry attempts

        Returns:
            Dict[str, Any]: API response data

        Raises:
            ValueError: If max retries exceeded or rate limit hit
            Exception: If API request fails
        """
        for attempt in range(max_retries):
            try:
                return await self._make_request(url, params, endpoint)
            except aiohttp.ClientError as e:
                await self._handle_request_error(e, attempt, max_retries)
            except ValueError as e:
                raise e  # Re-raise validation errors
            except Exception as e:
                await self._handle_request_error(e, attempt, max_retries)

            # Wait before retrying
            await asyncio.sleep(1 * (attempt + 1))

    async def _make_request(
        self, url: str, params: Optional[Dict[str, Any]], endpoint: Optional[str]
    ) -> Dict[str, Any]:
        """Make a single API request

        Args:
            url: API endpoint URL
            params: Query parameters
            endpoint: API endpoint name for rate limiting

        Returns:
            Dict[str, Any]: API response data

        Raises:
            ValueError: If rate limit hit or response invalid
        """
        if endpoint:
            await self._check_rate_limit(endpoint)

        session = await self._get_session()
        async with session.get(url, params=params) as response:
            return await self._handle_response(response)

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Handle API response

        Args:
            response: API response object

        Returns:
            Dict[str, Any]: Response data

        Raises:
            ValueError: If response status is not 200
        """
        try:
            if response.status == 200:
                return await self._parse_json_response(response)

            error_handlers = {
                429: self._handle_rate_limit_error,
                403: self._handle_forbidden_error,
                404: self._handle_not_found_error,
            }

            handler = error_handlers.get(response.status, self._handle_unknown_error)
            raise await handler(response)

        except ValueError as e:
            raise e  # Re-raise validation errors
        except Exception as e:
            logger.error(f"Error handling response: {e}")
            raise ValueError("API 응답 처리에 실패했습니다") from e

    async def _parse_json_response(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Parse JSON response

        Args:
            response: API response object

        Returns:
            Dict[str, Any]: Parsed JSON data

        Raises:
            ValueError: If JSON parsing fails
        """
        try:
            return await response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise ValueError("API 응답을 파싱하는데 실패했습니다") from e

    async def _handle_rate_limit_error(self, response: aiohttp.ClientResponse) -> ValueError:
        """Handle rate limit error response

        Args:
            response: API response object

        Returns:
            ValueError: Formatted error
        """
        retry_after = response.headers.get("Retry-After", "60")
        return ValueError(f"API 호출 제한에 도달했습니다. {retry_after}초 후에 다시 시도해주세요.")

    async def _handle_forbidden_error(self, response: aiohttp.ClientResponse) -> ValueError:
        """Handle forbidden error response

        Args:
            response: API response object

        Returns:
            ValueError: Formatted error
        """
        return ValueError("API 키가 잘못되었거나 만료되었습니다")

    async def _handle_not_found_error(self, response: aiohttp.ClientResponse) -> ValueError:
        """Handle not found error response

        Args:
            response: API response object

        Returns:
            ValueError: Formatted error
        """
        return ValueError("요청한 리소스를 찾을 수 없습니다")

    async def _handle_unknown_error(self, response: aiohttp.ClientResponse) -> ValueError:
        """Handle unknown error response

        Args:
            response: API response object

        Returns:
            ValueError: Formatted error
        """
        return ValueError(f"API 요청이 실패했습니다 (상태 코드: {response.status})")

    async def _handle_request_error(self, error: Exception, attempt: int, max_retries: int) -> None:
        """Handle request errors

        Args:
            error: The error that occurred
            attempt: Current attempt number
            max_retries: Maximum number of retries

        Raises:
            ValueError: If max retries exceeded or network error
        """
        try:
            self._log_request_error(error, attempt)

            if self._is_final_attempt(attempt, max_retries):
                raise await self._create_final_error(error)

        except ValueError as e:
            raise e  # Re-raise user errors
        except Exception as e:
            logger.error(f"Unexpected error handling request error: {e}")
            raise ValueError("요청 처리 중 예상치 못한 오류가 발생했습니다") from e

    def _log_request_error(self, error: Exception, attempt: int) -> None:
        """Log request error details

        Args:
            error: The error that occurred
            attempt: Current attempt number
        """
        error_type = type(error).__name__
        logger.error(f"Request failed on attempt {attempt + 1}: " f"[{error_type}] {str(error)}")

    def _is_final_attempt(self, attempt: int, max_retries: int) -> bool:
        """Check if this is the final retry attempt

        Args:
            attempt: Current attempt number
            max_retries: Maximum number of retries

        Returns:
            bool: True if this is the final attempt
        """
        return attempt == max_retries - 1

    async def _create_final_error(self, error: Exception) -> ValueError:
        """Create final error message after all retries failed

        Args:
            error: The error that occurred

        Returns:
            ValueError: Formatted error message
        """
        if isinstance(error, aiohttp.ClientError):
            return ValueError("네트워크 연결에 실패했습니다. " "인터넷 연결을 확인해주세요.")

        return ValueError("최대 재시도 횟수를 초과했습니다. " "잠시 후 다시 시도해주세요.")

    @abstractmethod
    async def close(self):
        """Cleanup resources"""
        if self._session:
            if not self._session.closed:  # Add check
                await self._session.close()
            self._session = None

    async def _check_rate_limit(self, endpoint: str):
        """Check and enforce rate limits for the given endpoint

        Args:
            endpoint: API endpoint to check rate limits for

        Raises:
            ValueError: If rate limit is exceeded
        """
        try:
            if endpoint not in self._rate_limits:
                return

            config = self._rate_limits[endpoint]
            current_time = time.time()

            self._clean_old_timestamps(endpoint, current_time, config.period)
            await self._enforce_rate_limit(endpoint, current_time, config)

        except ValueError as e:
            raise e  # Re-raise rate limit errors
        except Exception as e:
            logger.error(f"Error checking rate limit for {endpoint}: {e}")
            raise ValueError(f"Rate limit check failed: {e}") from e

    def _clean_old_timestamps(self, endpoint: str, current_time: float, period: int):
        """Clean up old timestamps for an endpoint

        Args:
            endpoint: API endpoint
            current_time: Current timestamp
            period: Time period in seconds
        """
        self._request_timestamps[endpoint] = [
            ts for ts in self._request_timestamps[endpoint] if current_time - ts < period
        ]

    async def _enforce_rate_limit(
        self, endpoint: str, current_time: float, config: RateLimitConfig
    ):
        """Enforce rate limit for an endpoint

        Args:
            endpoint: API endpoint
            current_time: Current timestamp
            config: Rate limit configuration

        Raises:
            ValueError: If rate limit is exceeded
        """
        if len(self._request_timestamps[endpoint]) >= config.requests:
            wait_time = self._calculate_wait_time(endpoint, current_time, config)
            raise ValueError(
                f"Rate limit exceeded for {endpoint}. " f"Please wait {wait_time:.1f} seconds."
            )

        self._request_timestamps[endpoint].append(current_time)

    def _calculate_wait_time(
        self, endpoint: str, current_time: float, config: RateLimitConfig
    ) -> float:
        """Calculate wait time when rate limit is exceeded

        Args:
            endpoint: API endpoint
            current_time: Current timestamp
            config: Rate limit configuration

        Returns:
            float: Time to wait in seconds
        """
        return min(self._request_timestamps[endpoint]) + config.period - current_time

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
