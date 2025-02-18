import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

import google.generativeai as genai
from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)

class GeminiAPI(BaseAPI[str]):
    """Google Gemini API client implementation for text-only interactions"""

    # Token thresholds for Gemini 2.0 Flash
    MAX_TOTAL_TOKENS = 32000  # Maximum total tokens (prompt + response) per interaction
    MAX_PROMPT_TOKENS = 8000  # Maximum tokens for user input (reduced for typical Korean chat)
    TOKEN_WARNING_THRESHOLD = 0.8  # Warning at 80% of limit to provide safety margin
    RESPONSE_BUFFER_TOKENS = 2000  # Increased buffer for Korean responses
    REQUESTS_PER_MINUTE = 60  # Standard API rate limit
    DAILY_TOKEN_LIMIT = 1_000_000  # Local limit: 1M tokens per day
    
    # User-specific rate limits
    USER_REQUESTS_PER_MINUTE = 4  # Maximum requests per minute per user (every 15 seconds)
    USER_COOLDOWN_SECONDS = 5  # Cooldown period between requests for a user

    def __init__(self, api_key: str) -> None:
        """Initialize Gemini API client
        
        Args:
            api_key: Google API key for Gemini
        """
        super().__init__(api_key)
        self._model = None
        self._rate_limits = {
            "generate": RateLimitConfig(self.REQUESTS_PER_MINUTE, 60),  # 60 requests per minute for generate_content
        }
        # Usage tracking
        self._daily_requests = 0
        self._last_reset = datetime.now()
        self._request_sizes: List[int] = []  # Track request sizes
        self._hourly_token_count = 0  # Track token usage per hour (for monitoring only)
        self._last_token_reset = datetime.now()
        
        # Per-minute request tracking
        self._minute_requests = 0
        self._last_minute_reset = datetime.now()
        
        # User request tracking
        self._user_requests: Dict[int, List[datetime]] = {}  # user_id -> list of request timestamps
        
        # Detailed token tracking
        self._total_prompt_tokens = 0
        self._total_response_tokens = 0
        self._max_prompt_tokens = 0
        self._max_response_tokens = 0
        self._token_usage_history: List[Tuple[int, int]] = []  # (prompt_tokens, response_tokens)

    async def initialize(self) -> None:
        """Initialize Gemini API resources"""
        await super().initialize()
        # Configure the Gemini API
        genai.configure(api_key=self.api_key)
        # Initialize text-only model using Gemini 2.0 Flash
        self._model = genai.GenerativeModel('gemini-2.0-flash')

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using model's tokenizer
        
        Args:
            text: Text to count tokens for
            
        Returns:
            int: Number of tokens
            
        Raises:
            ValueError: If token counting fails
        """
        try:
            return self._model.count_tokens(text).total_tokens
        except Exception as e:
            logger.warning(f"Failed to count tokens accurately: {e}")
            # Fallback to rough estimation
            return len(text) // 4

    def _check_token_thresholds(self, prompt_tokens: int) -> None:
        """Check token thresholds and log warnings
        
        Args:
            prompt_tokens: Number of tokens in prompt
            
        Raises:
            ValueError: If token limits are exceeded
        """
        # Check prompt token limit
        if prompt_tokens > self.MAX_PROMPT_TOKENS:
            raise ValueError(
                f"입력이 너무 깁니다. 현재: {prompt_tokens:,} 토큰\n"
                f"최대 입력 길이: {self.MAX_PROMPT_TOKENS:,} 토큰\n"
                f"입력을 더 짧게 작성해주세요."
            )

        # Check if we have enough room for response with buffer
        estimated_max_response = self.MAX_TOTAL_TOKENS - prompt_tokens - self.RESPONSE_BUFFER_TOKENS
        if estimated_max_response < 1000:  # Minimum reasonable response length
            raise ValueError(
                f"입력이 너무 깁니다. 응답을 위한 공간이 부족합니다.\n"
                f"현재 입력: {prompt_tokens:,} 토큰\n"
                f"응답 가능 공간: {estimated_max_response:,} 토큰\n"
                f"입력을 더 짧게 작성해주세요."
            )

        # Check daily token limit
        daily_total = self._total_prompt_tokens + self._total_response_tokens
        estimated_total = daily_total + prompt_tokens + estimated_max_response
        if estimated_total > self.DAILY_TOKEN_LIMIT:
            hours_until_reset = 24 - (datetime.now() - self._last_reset).seconds // 3600
            raise ValueError(
                f"일일 토큰 한도에 도달했습니다.\n"
                f"현재 사용량: {daily_total:,} 토큰\n"
                f"예상 사용량: {estimated_total:,} 토큰\n"
                f"일일 한도: {self.DAILY_TOKEN_LIMIT:,} 토큰\n"
                f"리셋까지 남은 시간: {hours_until_reset}시간"
            )

        # Warning for approaching token limits
        if prompt_tokens > self.MAX_PROMPT_TOKENS * self.TOKEN_WARNING_THRESHOLD:
            logger.warning(
                f"Prompt approaching token limit: {prompt_tokens:,}/{self.MAX_PROMPT_TOKENS:,} "
                f"({prompt_tokens/self.MAX_PROMPT_TOKENS*100:.1f}%)"
            )

        if daily_total > self.DAILY_TOKEN_LIMIT * self.TOKEN_WARNING_THRESHOLD:
            logger.warning(
                f"Approaching daily token limit: {daily_total:,}/{self.DAILY_TOKEN_LIMIT:,} "
                f"({daily_total/self.DAILY_TOKEN_LIMIT*100:.1f}%)"
            )

    def _track_request(self, prompt: str, response: str) -> None:
        """Track API usage
        
        Args:
            prompt: User's input
            response: API response
        """
        current_time = datetime.now()

        # Reset daily counters if it's a new day
        if current_time - self._last_reset > timedelta(days=1):
            logger.info(
                f"Daily Gemini API usage summary:\n"
                f"- Total requests: {self._daily_requests}\n"
                f"- Total prompt tokens: {self._total_prompt_tokens}\n"
                f"- Total response tokens: {self._total_response_tokens}\n"
                f"- Max prompt tokens: {self._max_prompt_tokens}\n"
                f"- Max response tokens: {self._max_response_tokens}\n"
                f"- Average tokens per request: {(self._total_prompt_tokens + self._total_response_tokens) / max(1, self._daily_requests):.1f}"
            )
            self._daily_requests = 0
            self._request_sizes = []
            self._total_prompt_tokens = 0
            self._total_response_tokens = 0
            self._max_prompt_tokens = 0
            self._max_response_tokens = 0
            self._token_usage_history = []
            self._last_reset = current_time

        # Reset per-minute request counter if it's been a minute
        if current_time - self._last_minute_reset > timedelta(minutes=1):
            self._minute_requests = 0
            self._last_minute_reset = current_time

        # Reset hourly token counter if it's been an hour
        if current_time - self._last_token_reset > timedelta(hours=1):
            logger.info(f"Hourly token usage: {self._hourly_token_count}")
            self._hourly_token_count = 0
            self._last_token_reset = current_time

        # Track this request
        self._daily_requests += 1
        self._minute_requests += 1
        request_size = len(prompt.encode('utf-8')) + len(response.encode('utf-8'))
        self._request_sizes.append(request_size)

        # Get accurate token count
        prompt_tokens = self._count_tokens(prompt)
        response_tokens = self._count_tokens(response)
        total_tokens = prompt_tokens + response_tokens

        # Update token statistics
        self._hourly_token_count += total_tokens
        self._total_prompt_tokens += prompt_tokens
        self._total_response_tokens += response_tokens
        self._max_prompt_tokens = max(self._max_prompt_tokens, prompt_tokens)
        self._max_response_tokens = max(self._max_response_tokens, response_tokens)
        self._token_usage_history.append((prompt_tokens, response_tokens))

        # Log token details at debug level
        logger.debug(
            f"Token usage for request:\n"
            f"- Prompt tokens: {prompt_tokens:,}\n"
            f"- Response tokens: {response_tokens:,}\n"
            f"- Total tokens: {total_tokens:,}\n"
            f"- Requests this minute: {self._minute_requests}/{self.REQUESTS_PER_MINUTE}\n"
            f"- Hourly token total: {self._hourly_token_count:,}"
        )

    def _check_user_rate_limit(self, user_id: int) -> None:
        """Check if user has exceeded their rate limit
        
        Args:
            user_id: Discord user ID
            
        Raises:
            ValueError: If user has exceeded rate limit
        """
        current_time = datetime.now()
        
        # Initialize user's request history if not exists
        if user_id not in self._user_requests:
            self._user_requests[user_id] = []
            
        # Clean up old requests
        self._user_requests[user_id] = [
            timestamp for timestamp in self._user_requests[user_id]
            if (current_time - timestamp).total_seconds() < 60
        ]
        
        # Check requests per minute
        if len(self._user_requests[user_id]) >= self.USER_REQUESTS_PER_MINUTE:
            oldest_allowed = current_time - timedelta(minutes=1)
            next_available = self._user_requests[user_id][0] + timedelta(minutes=1)
            wait_seconds = (next_available - current_time).total_seconds()
            
            raise ValueError(
                f"요청이 너무 잦습니다.\n"
                f"분당 최대 {self.USER_REQUESTS_PER_MINUTE}회 요청 가능합니다.\n"
                f"다음 요청까지 {int(wait_seconds)}초 기다려주세요."
            )
        
        # Check cooldown between requests
        if self._user_requests[user_id]:
            last_request = self._user_requests[user_id][-1]
            seconds_since_last = (current_time - last_request).total_seconds()
            
            if seconds_since_last < self.USER_COOLDOWN_SECONDS:
                wait_seconds = self.USER_COOLDOWN_SECONDS - seconds_since_last
                raise ValueError(
                    f"요청간 간격이 너무 짧습니다.\n"
                    f"다음 요청까지 {int(wait_seconds)}초 기다려주세요."
                )
        
        # Add current request to history
        self._user_requests[user_id].append(current_time)

    async def chat(self, prompt: str, user_id: int) -> str:
        """Send a chat message to Gemini
        
        Args:
            prompt: The user's message (text only)
            user_id: Discord user ID

        Returns:
            str: Gemini's response

        Raises:
            ValueError: If the request fails or limits are exceeded
        """
        try:
            if not self._model:
                raise ValueError("Gemini API not initialized")

            # Check user rate limits
            self._check_user_rate_limit(user_id)

            # Check token limits before making request
            prompt_tokens = self._count_tokens(prompt)
            self._check_token_thresholds(prompt_tokens)

            # Make the text-only request with rate limiting
            response = await self._make_request(
                "",  # URL not needed as we're using the SDK
                endpoint="generate",  # Match the rate limit key
                custom_request=lambda: self._model.generate_content(prompt)
            )

            # Extract the text from the response
            if not response or not response.text:
                raise ValueError("Empty response from Gemini")

            # Track usage
            self._track_request(prompt, response.text)

            return response.text

        except ValueError:
            # Re-raise ValueError (including token limit errors)
            raise
        except Exception as e:
            logger.error(f"Error in Gemini chat: {e}")
            raise ValueError(f"Gemini API 요청에 실패했습니다: {str(e)}") from e

    @property
    def usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics
        
        Returns:
            Dict[str, Any]: Usage statistics
        """
        avg_prompt_tokens = self._total_prompt_tokens / max(1, self._daily_requests)
        avg_response_tokens = self._total_response_tokens / max(1, self._daily_requests)
        
        return {
            "daily_requests": self._daily_requests,
            "minute_requests": self._minute_requests,
            "hourly_tokens": self._hourly_token_count,
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_response_tokens": self._total_response_tokens,
            "max_prompt_tokens": self._max_prompt_tokens,
            "max_response_tokens": self._max_response_tokens,
            "avg_prompt_tokens": avg_prompt_tokens,
            "avg_response_tokens": avg_response_tokens,
            "last_reset": self._last_reset,
            "last_token_reset": self._last_token_reset,
            "last_minute_reset": self._last_minute_reset,
            "token_usage_history": self._token_usage_history[-10:],
            "avg_request_size": (
                sum(self._request_sizes) / len(self._request_sizes)
                if self._request_sizes else 0
            )
        }

    def get_formatted_report(self) -> str:
        """Generate a formatted, human-readable report of usage statistics
        
        Returns:
            str: Formatted report
        """
        stats = self.usage_stats
        current_time = datetime.now()
        
        # Calculate time until resets
        seconds_until_minute = 60 - (current_time - stats["last_minute_reset"]).seconds
        hours_until_daily = 24 - (current_time - stats["last_reset"]).seconds // 3600
        
        # Calculate daily totals and percentages
        daily_tokens = stats['total_prompt_tokens'] + stats['total_response_tokens']
        daily_token_percent = (daily_tokens / self.DAILY_TOKEN_LIMIT) * 100
        
        # Format the basic report
        report = [
            "📊 Gemini API 사용 현황",
            "",
            "🕒 현재 사용량:",
            f"  • 현재 분당 요청 수: {stats['minute_requests']:,}/{self.REQUESTS_PER_MINUTE}",
            f"  • 다음 분까지: {seconds_until_minute}초",
            f"  • 시간당 토큰: {stats['hourly_tokens']:,}",
            "",
            "📅 일간 사용량:",
            f"  • 총 요청 수: {stats['daily_requests']:,}회",
            f"  • 총 토큰: {daily_tokens:,}/{self.DAILY_TOKEN_LIMIT:,} ({daily_token_percent:.1f}%)",
            f"  • 남은 토큰: {self.DAILY_TOKEN_LIMIT - daily_tokens:,}",
            f"  • 다음 리셋까지: {hours_until_daily}시간",
            "",
            "📈 평균 통계:",
            f"  • 평균 요청당 토큰: {(stats['avg_prompt_tokens'] + stats['avg_response_tokens']):.1f}",
        ]
        
        # Add warnings
        warnings = []
        
        # Check request rate limit
        if stats['minute_requests'] > self.REQUESTS_PER_MINUTE * self.TOKEN_WARNING_THRESHOLD:
            warnings.append(
                f"⚠️ 분당 요청 한도의 {(stats['minute_requests']/self.REQUESTS_PER_MINUTE*100):.1f}%에 도달했습니다!"
            )
            
        # Check daily token limit
        if daily_token_percent > self.TOKEN_WARNING_THRESHOLD * 100:
            warnings.append(
                f"⚠️ 일일 토큰 한도의 {daily_token_percent:.1f}%에 도달했습니다!"
            )
            
        if warnings:
            report.extend(["", "⚠️ 경고:"] + [f"  • {w}" for w in warnings])
            
        return "\n".join(report)

    async def close(self) -> None:
        """Cleanup resources"""
        self._model = None
        await super().close() 