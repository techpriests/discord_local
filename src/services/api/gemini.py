import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

import google.generativeai as genai
from .base import BaseAPI, RateLimitConfig
import psutil
import asyncio
import discord

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

    # Add degradation thresholds
    ERROR_WINDOW_MINUTES = 5
    MAX_ERRORS_BEFORE_SLOWDOWN = 5
    MAX_ERRORS_BEFORE_DISABLE = 10
    
    # Add load thresholds
    CPU_THRESHOLD_PERCENT = 80
    MEMORY_THRESHOLD_PERCENT = 80
    
    # Add cooldown settings
    SLOWDOWN_COOLDOWN_MINUTES = 15
    DISABLE_COOLDOWN_MINUTES = 60

    def __init__(self, api_key: str, notification_channel: Optional[discord.TextChannel] = None) -> None:
        """Initialize Gemini API client
        
        Args:
            api_key: Google API key for Gemini
            notification_channel: Optional Discord channel for notifications
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

        # Add degradation state
        self._is_enabled = True
        self._is_slowed_down = False
        self._last_slowdown = None
        self._last_disable = None
        
        # Add error tracking
        self._recent_errors: List[datetime] = []
        self._error_count = 0
        
        # Add performance tracking
        self._cpu_usage = 0
        self._memory_usage = 0
        self._last_performance_check = datetime.now()

        # Add notification channel and cooldown tracking
        self._notification_channel = notification_channel
        self._last_notification_time: Dict[str, datetime] = {}  # Track last notification time per type

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

    async def _send_notification(
        self, 
        title: str, 
        description: str,
        notification_type: str,
        color: int = 0xFF0000,  # Red by default
        cooldown_minutes: int = 15
    ) -> None:
        """Send notification to Discord channel
        
        Args:
            title: Notification title
            description: Notification description
            notification_type: Type of notification for cooldown tracking
            color: Embed color (default: red)
            cooldown_minutes: Cooldown period for this notification type
        """
        if not self._notification_channel:
            return

        # Check cooldown
        current_time = datetime.now()
        last_notification = self._last_notification_time.get(notification_type)
        if last_notification:
            time_since_last = (current_time - last_notification).total_seconds() / 60
            if time_since_last < cooldown_minutes:
                return

        try:
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color(color),
                timestamp=current_time
            )

            await self._notification_channel.send(embed=embed)
            self._last_notification_time[notification_type] = current_time

        except Exception as e:
            logger.error(f"Error sending Discord notification: {e}")

    async def _notify_state_change(
        self, 
        state: str, 
        reason: str, 
        metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send state change notification
        
        Args:
            state: New state (e.g., "slowdown", "disabled")
            reason: Reason for state change
            metrics: Optional metrics to include
        """
        title = f"🤖 Gemini AI Service {state.title()}"
        
        description = [f"**Reason:** {reason}"]
        
        if metrics:
            description.append("\n**Current Metrics:**")
            for key, value in metrics.items():
                if isinstance(value, float):
                    description.append(f"• {key}: {value:.1f}")
                else:
                    description.append(f"• {key}: {value}")

        color = 0xFFA500 if state == "slowdown" else 0xFF0000  # Orange for slowdown, Red for disabled
        
        await self._send_notification(
            title=title,
            description="\n".join(description),
            notification_type=f"state_{state}",
            color=color,
            cooldown_minutes=30  # Longer cooldown for state changes
        )

    async def _check_system_health(self) -> None:
        """Check system health and update degradation state"""
        current_time = datetime.now()
        
        # Only check every minute
        if (current_time - self._last_performance_check).total_seconds() < 60:
            return
            
        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
            
            self._cpu_usage = cpu_percent
            self._memory_usage = memory_percent
            self._last_performance_check = current_time
            
            # Check if we should exit slowdown
            if self._is_slowed_down and self._last_slowdown:
                if (current_time - self._last_slowdown).total_seconds() > self.SLOWDOWN_COOLDOWN_MINUTES * 60:
                    if cpu_percent < self.CPU_THRESHOLD_PERCENT and memory_percent < self.MEMORY_THRESHOLD_PERCENT:
                        self._is_slowed_down = False
                        self._last_slowdown = None
                        logger.info("Exiting slowdown mode - system resources normalized")
                        await self._notify_state_change(
                            "recovered",
                            "System resources have normalized",
                            {"CPU Usage": cpu_percent, "Memory Usage": memory_percent}
                        )
            
            # Check if we should exit disabled state
            if not self._is_enabled and self._last_disable:
                if (current_time - self._last_disable).total_seconds() > self.DISABLE_COOLDOWN_MINUTES * 60:
                    if cpu_percent < self.CPU_THRESHOLD_PERCENT and memory_percent < self.MEMORY_THRESHOLD_PERCENT:
                        self._is_enabled = True
                        self._last_disable = None
                        logger.info("Re-enabling Gemini API - system resources normalized")
                        await self._notify_state_change(
                            "enabled",
                            "Service has been re-enabled after recovery",
                            {"CPU Usage": cpu_percent, "Memory Usage": memory_percent}
                        )
            
            # Check if we need to degrade
            if cpu_percent > self.CPU_THRESHOLD_PERCENT or memory_percent > self.MEMORY_THRESHOLD_PERCENT:
                if not self._is_slowed_down:
                    self._is_slowed_down = True
                    self._last_slowdown = current_time
                    logger.warning(
                        f"Entering slowdown mode - CPU: {cpu_percent}%, Memory: {memory_percent}%"
                    )
                    await self._notify_state_change(
                        "slowdown",
                        "High system resource usage detected",
                        {
                            "CPU Usage": cpu_percent,
                            "Memory Usage": memory_percent,
                            "Duration": f"{self.SLOWDOWN_COOLDOWN_MINUTES} minutes"
                        }
                    )
                elif not self._last_disable:
                    self._is_enabled = False
                    self._last_disable = current_time
                    logger.error(
                        f"Disabling Gemini API - CPU: {cpu_percent}%, Memory: {memory_percent}%"
                    )
                    await self._notify_state_change(
                        "disabled",
                        "Critical system resource usage",
                        {
                            "CPU Usage": cpu_percent,
                            "Memory Usage": memory_percent,
                            "Duration": f"{self.DISABLE_COOLDOWN_MINUTES} minutes"
                        }
                    )
        
        except Exception as e:
            logger.error(f"Error checking system health: {e}")

    def _track_error(self) -> None:
        """Track API errors and update degradation state"""
        current_time = datetime.now()
        
        # Clean up old errors
        self._recent_errors = [
            timestamp for timestamp in self._recent_errors
            if (current_time - timestamp).total_seconds() < self.ERROR_WINDOW_MINUTES * 60
        ]
        
        # Add new error
        self._recent_errors.append(current_time)
        self._error_count = len(self._recent_errors)
        
        # Check if we need to degrade
        if self._error_count >= self.MAX_ERRORS_BEFORE_DISABLE:
            if self._is_enabled:
                self._is_enabled = False
                self._last_disable = current_time
                logger.error(
                    f"Disabling Gemini API - {self._error_count} errors in {self.ERROR_WINDOW_MINUTES} minutes"
                )
                asyncio.create_task(self._notify_state_change(
                    "disabled",
                    f"Too many errors ({self._error_count} in {self.ERROR_WINDOW_MINUTES} minutes)",
                    {
                        "Error Count": self._error_count,
                        "Window": f"{self.ERROR_WINDOW_MINUTES} minutes",
                        "Duration": f"{self.DISABLE_COOLDOWN_MINUTES} minutes"
                    }
                ))
        elif self._error_count >= self.MAX_ERRORS_BEFORE_SLOWDOWN:
            if not self._is_slowed_down:
                self._is_slowed_down = True
                self._last_slowdown = current_time
                logger.warning(
                    f"Entering slowdown mode - {self._error_count} errors in {self.ERROR_WINDOW_MINUTES} minutes"
                )
                asyncio.create_task(self._notify_state_change(
                    "slowdown",
                    f"High error rate ({self._error_count} in {self.ERROR_WINDOW_MINUTES} minutes)",
                    {
                        "Error Count": self._error_count,
                        "Window": f"{self.ERROR_WINDOW_MINUTES} minutes",
                        "Duration": f"{self.SLOWDOWN_COOLDOWN_MINUTES} minutes"
                    }
                ))

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
            # Check system health
            await self._check_system_health()
            
            # Check if service is enabled
            if not self._is_enabled:
                raise ValueError(
                    "AI 서비스가 일시적으로 비활성화되었습니다. "
                    f"약 {self.DISABLE_COOLDOWN_MINUTES}분 후에 다시 시도해주세요."
                )
            
            # Apply slowdown if needed
            if self._is_slowed_down:
                await asyncio.sleep(5)  # Add 5 second delay
            
            # Existing validation
            if not self._model:
                raise ValueError("Gemini API not initialized")

            # Check user rate limits
            self._check_user_rate_limit(user_id)

            # Check token limits
            prompt_tokens = self._count_tokens(prompt)
            self._check_token_thresholds(prompt_tokens)

            # Make the request with rate limiting
            response = await self._make_request(
                "",
                endpoint="generate",
                custom_request=lambda: self._model.generate_content(prompt)
            )

            # Validate response
            if not response or not response.text:
                raise ValueError("Empty response from Gemini")

            # Track usage
            self._track_request(prompt, response.text)

            return response.text

        except Exception as e:
            # Track error for degradation
            self._track_error()
            
            # Re-raise with appropriate message
            if isinstance(e, ValueError):
                raise
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

    @property
    def health_status(self) -> Dict[str, Any]:
        """Get current health status
        
        Returns:
            Dict[str, Any]: Health status information
        """
        current_time = datetime.now()
        
        return {
            "is_enabled": self._is_enabled,
            "is_slowed_down": self._is_slowed_down,
            "error_count": self._error_count,
            "cpu_usage": self._cpu_usage,
            "memory_usage": self._memory_usage,
            "time_until_slowdown_reset": (
                None if not self._last_slowdown else
                max(0, self.SLOWDOWN_COOLDOWN_MINUTES * 60 - 
                    (current_time - self._last_slowdown).total_seconds())
            ),
            "time_until_enable": (
                None if not self._last_disable else
                max(0, self.DISABLE_COOLDOWN_MINUTES * 60 - 
                    (current_time - self._last_disable).total_seconds())
            )
        }

    async def close(self) -> None:
        """Cleanup resources"""
        self._model = None
        await super().close()

    async def validate_credentials(self) -> bool:
        """Validate Gemini API credentials
        
        Returns:
            bool: True if credentials are valid
        """
        try:
            if not self.api_key:
                return False
                
            # Configure the API
            genai.configure(api_key=self.api_key)
            
            # Try to initialize the model
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # Try a simple test request
            response = await self._make_request(
                "",
                endpoint="generate",
                custom_request=lambda: model.generate_content("test")
            )
            
            return bool(response and response.text)
            
        except Exception as e:
            logger.error(f"Failed to validate Gemini credentials: {e}")
            return False 