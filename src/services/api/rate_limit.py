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
