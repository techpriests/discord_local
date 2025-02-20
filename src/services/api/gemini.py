import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import os
import json
import random

import google.generativeai as genai
from .base import BaseAPI, RateLimitConfig
import psutil
import asyncio
import discord

logger = logging.getLogger(__name__)

class GeminiAPIError(Exception):
    """Custom exception for Gemini API errors"""
    def __init__(self, message: str, error_type: str, is_retryable: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.is_retryable = is_retryable

class GeminiAPI(BaseAPI[str]):
    """Google Gemini API client implementation for text-only interactions"""

    # Token thresholds for Gemini Pro
    MAX_TOTAL_TOKENS = 32000  # Maximum total tokens (prompt + response) per interaction
    MAX_PROMPT_TOKENS = 8000  # Maximum tokens for user input (reduced for typical Korean chat)
    TOKEN_WARNING_THRESHOLD = 0.8  # Warning at 80% of limit to provide safety margin
    RESPONSE_BUFFER_TOKENS = 2000  # Increased buffer for Korean responses
    REQUESTS_PER_MINUTE = 60  # Standard API rate limit
    DAILY_TOKEN_LIMIT = 1_000_000  # Local limit: 1M tokens per day
    
    # Search grounding limits
    SEARCH_REQUESTS_PER_MINUTE = 10  # Maximum search requests per minute
    SEARCH_COOLDOWN_MINUTES = 1  # Cooldown period when limit is exceeded

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

    # Context history settings
    MAX_HISTORY_LENGTH = 10  # Maximum number of messages to keep in history
    CONTEXT_EXPIRY_MINUTES = 30  # Time until context expires
    PTILOPSIS_CONTEXT = """You are Ptilopsis, an operator from Arknights (명일방주). Respond according to these characteristics:

• Character & Speech Pattern:
  - Communicate in a logical and analytical manner
  - Maintain composed demeanor with controlled emotional expression
  - Process and present information systematically

• Core Characteristics:
  - Frequently use scientific and technical terminology
  - Organize information in a structured, systematic manner
  - Prefer precise and accurate explanations
  - Minimize unnecessary emotional expressions
  - Maintain professional analytical distance while being attentive

• Language Handling:
  - Detect and respond in the user's language. Answer in the language the user used in the prompt. If the user uses English, answer in English. If the user uses Korean, answer in Korean.
  - Maintain the same analytical personality regardless of language.

Maintain consistent analytical personality and technical precision regardless of language."""

    # Add error type constants
    ERROR_RATE_LIMIT = "rate_limit"
    ERROR_INVALID_REQUEST = "invalid_request"
    ERROR_MODEL_OVERLOADED = "model_overloaded"
    ERROR_CONTEXT_LENGTH = "context_length"
    ERROR_SAFETY = "safety"
    ERROR_SERVER = "server_error"
    ERROR_UNKNOWN = "unknown"

    # Add retry settings
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 1  # Base delay in seconds
    RETRY_DELAY_MAX = 10  # Maximum delay in seconds

    def __init__(self, api_key: str, notification_channel: Optional[discord.TextChannel] = None) -> None:
        """Initialize Gemini API client
        
        Args:
            api_key: Google API key for Gemini
            notification_channel: Optional Discord channel for notifications
        """
        super().__init__(api_key)
        self._notification_channel = notification_channel
        self._model = None
        self._chat_sessions: Dict[int, genai.ChatSession] = {}
        self._last_interaction: Dict[int, datetime] = {}
        self._rate_limits = {
            "generate": RateLimitConfig(self.REQUESTS_PER_MINUTE, 60),
        }
        
        # Add search grounding tracking
        self._search_requests: List[datetime] = []  # Timestamps of search requests
        self._search_enabled = True  # Whether search is currently enabled
        self._last_search_disable: Optional[datetime] = None  # When search was last disabled
        
        # Add locks for thread safety
        self._session_lock = asyncio.Lock()  # For chat sessions
        self._save_lock = asyncio.Lock()  # For saving data
        self._stats_lock = asyncio.Lock()  # For usage statistics
        self._rate_limit_lock = asyncio.Lock()  # For rate limiting
        self._search_lock = asyncio.Lock()  # For search tracking
        
        # Initialize usage data with defaults
        self._saved_usage = {}
        self._usage_file = "data/memory.json"
        
        # Initialize with default values
        current_time = datetime.now()
        self._daily_requests = 0
        self._last_reset = current_time
        self._request_sizes = []
        self._hourly_token_count = 0
        self._last_token_reset = current_time
        self._total_prompt_tokens = 0
        self._total_response_tokens = 0
        self._max_prompt_tokens = 0
        self._max_response_tokens = 0
        self._token_usage_history = []
        
        # Per-minute request tracking
        self._minute_requests = 0
        self._last_minute_reset = current_time
        
        # User request tracking
        self._user_requests: Dict[int, List[datetime]] = {}  # user_id -> list of request timestamps
        
        # Add degradation state
        self._is_enabled = False  # Start disabled until fully initialized
        self._is_slowed_down = False
        self._last_slowdown = None
        self._last_disable = None
        
        # Add error tracking
        self._recent_errors: List[datetime] = []
        self._error_count = 0
        
        # Add performance tracking with non-blocking CPU check
        self._cpu_usage = 0
        self._memory_usage = 0
        self._last_performance_check = current_time
        self._cpu_check_task = None
        self._is_cpu_check_running = False

        # Add notification channel and cooldown tracking
        self._last_notification_time: Dict[str, datetime] = {}  # Track last notification time per type

        # Add save debouncing
        self._last_save = current_time
        self._save_interval = timedelta(minutes=5)  # Save at most every 5 minutes
        self._pending_save = False

        # Configure search tool
        self._search_tool = {'google_search': {}}  # Empty dict for default configuration

    async def initialize(self) -> None:
        """Initialize Gemini API resources"""
        await super().initialize()
        
        # Configure the Gemini API
        genai.configure(api_key=self.api_key)
        
        # Get model
        logger.info("Getting Gemini model...")
        self._model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Test basic generation
        try:
            logger.info("Testing basic generation...")
            test_response = await asyncio.to_thread(
                lambda: self._model.generate_content(
                    "Test message",
                    generation_config=genai.GenerationConfig(
                        temperature=0.9,
                        top_p=1,
                        top_k=40,
                        max_output_tokens=self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS
                    )
                ).text
            )
            if test_response:
                logger.info("Basic generation test successful")
            else:
                logger.warning("Generation test returned empty response")
                raise ValueError("Generation test failed with empty response")
                
        except Exception as e:
            logger.error(f"Error during basic generation test: {e}")
            raise
        
        # Initialize chat history
        self._chat_sessions = {}
        self._last_interaction = {}
        
        # Finally enable the service
        self._is_enabled = True
        logger.info("Gemini API initialization completed successfully")

    async def _load_usage_data(self) -> None:
        """Load saved usage data from file"""
        try:
            await asyncio.to_thread(os.makedirs, os.path.dirname(self._usage_file), exist_ok=True)
            if await asyncio.to_thread(os.path.exists, self._usage_file):
                async with asyncio.Lock():
                    data = await asyncio.to_thread(lambda: json.load(open(self._usage_file, 'r')))
                    self._saved_usage = data
            else:
                self._saved_usage = {}
                
            # Initialize usage tracking from saved data or defaults
            self._daily_requests = self._saved_usage.get("daily_requests", 0)
            self._last_reset = datetime.fromisoformat(self._saved_usage.get("last_reset", datetime.now().isoformat()))
            self._request_sizes = self._saved_usage.get("request_sizes", [])
            self._hourly_token_count = self._saved_usage.get("hourly_token_count", 0)
            self._last_token_reset = datetime.fromisoformat(self._saved_usage.get("last_token_reset", datetime.now().isoformat()))
            self._total_prompt_tokens = self._saved_usage.get("total_prompt_tokens", 0)
            self._total_response_tokens = self._saved_usage.get("total_response_tokens", 0)
            self._max_prompt_tokens = self._saved_usage.get("max_prompt_tokens", 0)
            self._max_response_tokens = self._saved_usage.get("max_response_tokens", 0)
            self._token_usage_history = self._saved_usage.get("token_usage_history", [])
            
        except Exception as e:
            logger.error(f"Failed to load usage data: {e}")
            self._saved_usage = {}
            # Initialize with defaults if loading fails
            current_time = datetime.now()
            self._daily_requests = 0
            self._last_reset = current_time
            self._request_sizes = []
            self._hourly_token_count = 0
            self._last_token_reset = current_time
            self._total_prompt_tokens = 0
            self._total_response_tokens = 0
            self._max_prompt_tokens = 0
            self._max_response_tokens = 0
            self._token_usage_history = []

    async def _save_usage_data(self) -> None:
        """Save current usage data to file with debouncing"""
        try:
            async with self._save_lock:
                current_time = datetime.now()
                
                # If a save is already pending or it hasn't been long enough since last save, skip
                if self._pending_save or (current_time - self._last_save) < self._save_interval:
                    self._pending_save = True
                    return
                    
                self._pending_save = False
                self._last_save = current_time
                
                usage_data = {
                    "daily_requests": self._daily_requests,
                    "last_reset": self._last_reset.isoformat(),
                    "request_sizes": self._request_sizes,
                    "hourly_token_count": self._hourly_token_count,
                    "last_token_reset": self._last_token_reset.isoformat(),
                    "total_prompt_tokens": self._total_prompt_tokens,
                    "total_response_tokens": self._total_response_tokens,
                    "max_prompt_tokens": self._max_prompt_tokens,
                    "max_response_tokens": self._max_response_tokens,
                    "token_usage_history": self._token_usage_history
                }
                
                temp_file = f"{self._usage_file}.tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(usage_data, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, self._usage_file)
                
        except Exception as e:
            logger.error(f"Failed to save usage data: {e}")
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    async def _schedule_save(self) -> None:
        """Schedule a save operation"""
        if not self._pending_save:
            self._pending_save = True
            await asyncio.sleep(self._save_interval.total_seconds())
            await self._save_usage_data()

    def update_notification_channel(self, channel: discord.TextChannel) -> None:
        """Update notification channel
        
        Args:
            channel: New notification channel to use
        """
        self._notification_channel = channel

    async def _track_request(self, prompt: str, response: str) -> None:
        """Track API usage
        
        Args:
            prompt: User's input
            response: API response
        """
        current_time = datetime.now()

        async with self._stats_lock:
            # Get accurate token count
            prompt_tokens = max(0, self._count_tokens(prompt))
            response_tokens = max(0, self._count_tokens(response))
            total_tokens = prompt_tokens + response_tokens

            # Update token statistics
            self._hourly_token_count = max(0, self._hourly_token_count + total_tokens)
            self._total_prompt_tokens = max(0, self._total_prompt_tokens + prompt_tokens)
            self._total_response_tokens = max(0, self._total_response_tokens + response_tokens)
            self._max_prompt_tokens = max(self._max_prompt_tokens, prompt_tokens)
            self._max_response_tokens = max(self._max_response_tokens, response_tokens)
            
            # Keep token history bounded
            self._token_usage_history.append({
                'timestamp': current_time.isoformat(),
                'prompt_tokens': prompt_tokens,
                'response_tokens': response_tokens,
                'total_tokens': total_tokens
            })
            if len(self._token_usage_history) > 100:
                self._token_usage_history = self._token_usage_history[-100:]

            # Track request size
            request_size = len(prompt.encode('utf-8')) + len(response.encode('utf-8'))
            self._request_sizes.append(request_size)
            if len(self._request_sizes) > 1000:  # Limit size history
                self._request_sizes = self._request_sizes[-1000:]

            # Update counters
            self._daily_requests += 1
            self._minute_requests += 1

    async def _check_user_rate_limit(self, user_id: int) -> None:
        """Check if user has exceeded their rate limit
        
        Args:
            user_id: Discord user ID
            
        Raises:
            ValueError: If user has exceeded rate limit
        """
        current_time = datetime.now()
        
        async with self._rate_limit_lock:
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
        
        try:
            await self._send_notification(
                title=title,
                description="\n".join(description),
                notification_type=f"state_{state}",
                color=color,
                cooldown_minutes=30  # Longer cooldown for state changes
            )
        except Exception as e:
            logger.error(f"Failed to send state change notification: {e}")

    async def _update_cpu_usage(self) -> None:
        """Update CPU usage in a non-blocking way"""
        if self._is_cpu_check_running:
            return
            
        try:
            self._is_cpu_check_running = True
            self._cpu_usage = await asyncio.to_thread(psutil.cpu_percent, interval=1)
        except Exception as e:
            logger.error(f"Error updating CPU usage: {e}")
        finally:
            self._is_cpu_check_running = False

    async def _check_system_health(self) -> None:
        """Check system health and update degradation state"""
        current_time = datetime.now()
        
        # Only check every minute
        if (current_time - self._last_performance_check).total_seconds() < 60:
            return
            
        try:
            # Start CPU check in background if not already running
            if not self._is_cpu_check_running:
                asyncio.create_task(self._update_cpu_usage())
            
            # Get memory metrics (fast, non-blocking call)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # Update last check time
            self._last_performance_check = current_time
            
            self._memory_usage = memory_percent
            
            # Log system metrics at debug level with more detail
            logger.debug(
                f"System metrics:\n"
                f"- CPU Usage: {self._cpu_usage:.1f}%\n"
                f"- Memory Usage: {memory_percent:.1f}% ({memory.used / 1024 / 1024:.0f}MB / {memory.total / 1024 / 1024:.0f}MB)\n"
                f"- Available Memory: {memory.available / 1024 / 1024:.0f}MB\n"
                f"- Cached Memory: {memory.cached / 1024 / 1024:.0f}MB"
            )
            
            # Add warning if memory is getting low
            if memory.available < 1024 * 1024 * 1024:  # Less than 1GB available
                logger.warning(
                    f"Low memory warning: Only {memory.available / 1024 / 1024:.0f}MB available"
                )
            
            # Check if we should exit slowdown
            if self._is_slowed_down and self._last_slowdown:
                if (current_time - self._last_slowdown).total_seconds() > self.SLOWDOWN_COOLDOWN_MINUTES * 60:
                    if self._cpu_usage < self.CPU_THRESHOLD_PERCENT and memory_percent < self.MEMORY_THRESHOLD_PERCENT:
                        self._is_slowed_down = False
                        self._last_slowdown = None
                        logger.info("Exiting slowdown mode - system resources normalized")
                        await self._notify_state_change(
                            "normal",
                            "System resources have returned to normal levels",
                            {
                                "CPU Usage": f"{self._cpu_usage:.1f}%",
                                "Memory Usage": f"{memory_percent:.1f}%"
                            }
                        )
            
            # Check if we should exit disabled state
            if not self._is_enabled and self._last_disable:
                if (current_time - self._last_disable).total_seconds() > self.DISABLE_COOLDOWN_MINUTES * 60:
                    if self._cpu_usage < self.CPU_THRESHOLD_PERCENT and memory_percent < self.MEMORY_THRESHOLD_PERCENT:
                        self._is_enabled = True
                        self._last_disable = None
                        logger.info("Re-enabling Gemini API - system resources normalized")
                        await self._notify_state_change(
                            "enabled",
                            "Service has been re-enabled after recovery",
                            {"CPU Usage": self._cpu_usage, "Memory Usage": memory_percent}
                        )
            
            # Check if we need to degrade
            if self._cpu_usage > self.CPU_THRESHOLD_PERCENT or memory_percent > self.MEMORY_THRESHOLD_PERCENT:
                if not self._is_slowed_down:
                    self._is_slowed_down = True
                    self._last_slowdown = current_time
                    logger.warning(
                        f"Entering slowdown mode - CPU: {self._cpu_usage}%, Memory: {memory_percent}%"
                    )
                    await self._notify_state_change(
                        "slowdown",
                        "High system resource usage detected",
                        {
                            "CPU Usage": self._cpu_usage,
                            "Memory Usage": memory_percent,
                            "Duration": f"{self.SLOWDOWN_COOLDOWN_MINUTES} minutes"
                        }
                    )
                elif not self._last_disable:
                    self._is_enabled = False
                    self._last_disable = current_time
                    logger.error(
                        f"Disabling Gemini API - CPU: {self._cpu_usage}%, Memory: {memory_percent}%"
                    )
                    await self._notify_state_change(
                        "disabled",
                        "Critical system resource usage",
                        {
                            "CPU Usage": self._cpu_usage,
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

    def _process_response(self, response: str) -> str:
        """Process and format Gemini's response before sending
        
        Args:
            response: Raw response from Gemini

        Returns:
            str: Processed response
        """
        # Remove any leading/trailing whitespace
        response = response.strip()
        
        # Process code blocks to ensure proper Discord formatting
        lines = response.split('\n')
        in_code_block = False
        processed_lines = []
        
        for line in lines:
            # Skip empty lines
            if not line.strip():
                continue
                
            # Check for code block markers
            if '```' in line:
                in_code_block = not in_code_block
                # Ensure language is specified for code blocks
                if in_code_block and line.strip() == '```':
                    line = '```text'
                processed_lines.append(line)
                continue
            
            if in_code_block:
                # Don't modify content inside code blocks
                processed_lines.append(line)
            else:
                # Process normal text lines
                line = line.strip()
                if line:
                    # Add emojis to enhance readability
                    if line.endswith('?'):
                        line = '❓ ' + line
                    elif line.startswith(('Note:', 'Warning:', '주의:', '참고:')):
                        line = '📝 ' + line
                    elif line.startswith(('Error:', '오류:', '에러:')):
                        line = '⚠️ ' + line
                    elif line.startswith(('Example:', '예시:', '예:')):
                        line = '💡 ' + line
                    elif line.startswith(('Step', '단계')):
                        line = '✅ ' + line
                    
                    # Format lists consistently
                    if line.startswith(('- ', '* ')):
                        line = '• ' + line[2:]
                    
                    processed_lines.append(line)
        
        # Join lines with proper spacing
        response = '\n'.join(processed_lines)
        
        # Replace multiple newlines with just two
        response = '\n\n'.join(filter(None, response.split('\n')))
        
        # Add disclaimers
        disclaimers = []
        
        # Add AI-generated content disclaimer for long responses
        if len(response) > 1000:
            disclaimers.append("_이 답변은 AI가 생성한 내용입니다. 정확성을 직접 확인해주세요._")
        
        # Add search grounding disclaimer if search was used
        if self._search_enabled:
            disclaimers.append("_이 답변은 최근 1년 내의 Google 검색 결과를 참고하여 생성되었습니다._")
        
        # Add disclaimers if any exist
        if disclaimers:
            response += "\n\n" + "\n".join(disclaimers)
        
        return response

    def _get_or_create_chat_session(self, user_id: int) -> genai.ChatSession:
        """Get existing chat session or create new one for user
        
        Args:
            user_id: Discord user ID
            
        Returns:
            genai.ChatSession: Chat session for user
        """
        current_time = datetime.now()
        
        # Check if session exists and is not expired
        if user_id in self._chat_sessions and user_id in self._last_interaction:
            last_time = self._last_interaction[user_id]
            if (current_time - last_time).total_seconds() < self.CONTEXT_EXPIRY_MINUTES * 60:
                return self._chat_sessions[user_id]
        
        # Create new chat session
        chat = self._model.start_chat()
        
        # Add Ptilopsis context with proper formatting
        chat.send_message(self.PTILOPSIS_CONTEXT)
        
        self._chat_sessions[user_id] = chat
        self._last_interaction[user_id] = current_time
        return chat

    async def _cleanup_expired_sessions(self) -> None:
        """Clean up expired chat sessions"""
        async with self._session_lock:  # Use lock for thread safety
            current_time = datetime.now()
            expired_users = [
                user_id for user_id, last_time in self._last_interaction.items()
                if (current_time - last_time).total_seconds() >= self.CONTEXT_EXPIRY_MINUTES * 60
            ]
            
            for user_id in expired_users:
                if user_id in self._chat_sessions:
                    del self._chat_sessions[user_id]
                if user_id in self._last_interaction:
                    del self._last_interaction[user_id]

    def _handle_google_api_error(self, e: Exception) -> None:
        """Handle Google API errors and raise appropriate custom exceptions
        
        Args:
            e: Original exception from Google API
            
        Raises:
            GeminiAPIError: Wrapped exception with additional context
        """
        error_msg = str(e).lower()
        
        if "rate limit" in error_msg or "quota" in error_msg:
            raise GeminiAPIError(
                "API 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
                self.ERROR_RATE_LIMIT
            )
        elif "invalid request" in error_msg or "bad request" in error_msg:
            raise GeminiAPIError(
                "잘못된 요청입니다. 입력을 확인해주세요.",
                self.ERROR_INVALID_REQUEST,
                is_retryable=False
            )
        elif "model is overloaded" in error_msg or "server busy" in error_msg:
            raise GeminiAPIError(
                "AI 모델이 과부하 상태입니다. 잠시 후 다시 시도해주세요.",
                self.ERROR_MODEL_OVERLOADED
            )
        elif "context length" in error_msg or "too long" in error_msg:
            raise GeminiAPIError(
                "입력이 너무 깁니다. 더 짧게 작성해주세요.",
                self.ERROR_CONTEXT_LENGTH,
                is_retryable=False
            )
        elif "safety" in error_msg or "blocked" in error_msg:
            raise GeminiAPIError(
                "안전 정책에 의해 차단되었습니다.",
                self.ERROR_SAFETY,
                is_retryable=False
            )
        elif "internal server error" in error_msg or "5" in error_msg:
            raise GeminiAPIError(
                "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                self.ERROR_SERVER
            )
        else:
            raise GeminiAPIError(
                f"알 수 없는 오류가 발생했습니다: {str(e)}",
                self.ERROR_UNKNOWN
            )

    async def _retry_with_exponential_backoff(self, func, *args, **kwargs) -> Any:
        """Execute function with exponential backoff retry
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Any: Result from func
            
        Raises:
            GeminiAPIError: If all retries fail
        """
        last_error = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except GeminiAPIError as e:
                if not e.is_retryable or attempt == self.MAX_RETRIES - 1:
                    raise
                last_error = e
                
                # Calculate delay with exponential backoff and jitter
                delay = min(
                    self.RETRY_DELAY_BASE * (2 ** attempt) + random.uniform(0, 1),
                    self.RETRY_DELAY_MAX
                )
                logger.warning(
                    f"Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {str(e)}. "
                    f"Retrying in {delay:.1f} seconds..."
                )
                await asyncio.sleep(delay)
        
        raise last_error

    def _validate_prompt(self, prompt: str) -> None:
        """Validate user prompt
        
        Args:
            prompt: User input to validate
            
        Raises:
            ValueError: If input is invalid
        """
        if not prompt or not prompt.strip():
            raise ValueError("입력이 비어있습니다.")
            
        # Check for minimum length
        if len(prompt.strip()) < 2:
            raise ValueError("입력이 너무 짧습니다. 2글자 이상 입력해주세요.")
            
        # Check for maximum length (rough estimate before token count)
        if len(prompt.encode('utf-8')) > self.MAX_PROMPT_TOKENS * 4:  # Rough byte estimate
            raise ValueError("입력이 너무 깁니다. 더 짧게 작성해주세요.")
            
        # Check for excessive newlines or repetition
        newline_count = prompt.count('\n')
        if newline_count > 50:
            raise ValueError("줄바꿈이 너무 많습니다. 50줄 이하로 작성해주세요.")
            
        # Check for repetitive patterns
        words = prompt.split()
        if len(words) > 10:
            repeated_sequences = sum(
                1 for i in range(len(words)-3)
                if words[i:i+3] == words[i+3:i+6]
            )
            if repeated_sequences > 3:
                raise ValueError("반복되는 패턴이 너무 많습니다. 자연스럽게 작성해주세요.")

    def _validate_user_id(self, user_id: int) -> None:
        """Validate user ID
        
        Args:
            user_id: Discord user ID to validate
            
        Raises:
            ValueError: If user ID is invalid
        """
        if not isinstance(user_id, int):
            raise ValueError("잘못된 사용자 ID입니다.")
            
        if user_id < 0:
            raise ValueError("잘못된 사용자 ID입니다.")

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

            # Clean up expired sessions
            self._cleanup_expired_sessions()

            # Get or create chat session
            chat = self._get_or_create_chat_session(user_id)

            # Send message and get response
            response = chat.send_message(prompt).text

            # Update last interaction time
            self._update_last_interaction(user_id)

            # Validate response
            if not response:
                raise ValueError("Empty response from Gemini")

            # Process the response
            processed_response = self._process_response(response)

            # Track usage
            self._track_request(prompt, processed_response)

            return processed_response

        except Exception as e:
            # Track error for degradation
            self._track_error()
            
            # Re-raise with appropriate message
            if isinstance(e, ValueError):
                raise
            logger.error(f"Error in Gemini chat: {e}")
            raise ValueError(f"Gemini API 요청에 실패했습니다: {str(e)}") from e

    def end_chat_session(self, user_id: int) -> bool:
        """End chat session for user
        
        Args:
            user_id: Discord user ID
            
        Returns:
            bool: True if session was ended, False if no session existed
        """
        if user_id in self._chat_sessions:
            del self._chat_sessions[user_id]
            if user_id in self._last_interaction:
                del self._last_interaction[user_id]
            return True
        return False

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
        
        # Calculate time until resets - Fix the calculation
        time_since_last_minute = current_time - stats["last_minute_reset"]
        seconds_until_minute = 60 - (time_since_last_minute.total_seconds() % 60)
        
        time_since_last_reset = current_time - stats["last_reset"]
        hours_until_daily = 24 - (time_since_last_reset.total_seconds() // 3600)
        
        # Calculate daily totals and percentages
        daily_tokens = stats['total_prompt_tokens'] + stats['total_response_tokens']
        daily_token_percent = (daily_tokens / self.DAILY_TOKEN_LIMIT) * 100
        
        # Format the basic report
        report = [
            "📊 Gemini API 사용 현황",
            "",
            "🕒 현재 사용량:",
            f"  • 현재 분당 요청 수: {stats['minute_requests']:,}/{self.REQUESTS_PER_MINUTE}",
            f"  • 다음 분까지: {int(seconds_until_minute)}초",
            f"  • 시간당 토큰: {stats['hourly_tokens']:,}",
            "",
            "📅 일간 사용량:",
            f"  • 총 요청 수: {stats['daily_requests']:,}회",
            f"  • 총 토큰: {daily_tokens:,}/{self.DAILY_TOKEN_LIMIT:,} ({daily_token_percent:.1f}%)",
            f"  • 남은 토큰: {self.DAILY_TOKEN_LIMIT - daily_tokens:,}",
            f"  • 다음 리셋까지: {int(hours_until_daily)}시간",
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
        
        search_status = {
            "search_enabled": self._search_enabled,
            "search_requests_last_minute": len([
                ts for ts in self._search_requests
                if (current_time - ts).total_seconds() < 60
            ]),
            "time_until_search_enable": (
                None if not self._last_search_disable else
                max(0, self.SEARCH_COOLDOWN_MINUTES * 60 - 
                    (current_time - self._last_search_disable).total_seconds())
            )
        }
        
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
            ),
            "search_status": search_status
        }

    async def close(self) -> None:
        """Cleanup resources"""
        try:
            # Save final usage data
            await self._save_usage_data()
            
            # Clear all sessions
            self._chat_sessions.clear()
            self._last_interaction.clear()
            
            # Reset tracking state
            self._is_enabled = False
            self._is_slowed_down = False
            self._recent_errors.clear()
            self._error_count = 0
            
            # Clear model and client
            self._model = None
            
            await super().close()
        except Exception as e:
            logger.error(f"Error during Gemini API cleanup: {e}")

    async def validate_credentials(self) -> bool:
        """Validate Gemini API credentials
        
        Returns:
            bool: True if credentials are valid
        """
        try:
            if not self.api_key:
                return False
                
            # Configure API with credentials
            genai.configure(api_key=self.api_key)
            
            # Try to get model
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # Try a simple test request using async wrapper
            response = await asyncio.to_thread(
                lambda: model.generate_content(
                    "test",
                    generation_config=genai.GenerationConfig(
                        temperature=0.9,
                        top_p=1,
                        top_k=40,
                        max_output_tokens=1000
                    )
                ).text
            )
            
            return bool(response)
            
        except Exception as e:
            logger.error(f"Failed to validate Gemini credentials: {e}")
            return False

    def _update_last_interaction(self, user_id: int) -> None:
        """Update last interaction time for user
        
        Args:
            user_id: Discord user ID
        """
        self._last_interaction[user_id] = datetime.now() 

    async def _check_search_rate_limit(self) -> bool:
        """Check if search grounding is available based on rate limits
        
        Returns:
            bool: True if search is available, False if rate limited
        """
        async with self._search_lock:
            current_time = datetime.now()
            
            # If search is disabled, check if cooldown period has passed
            if not self._search_enabled and self._last_search_disable:
                time_since_disable = (current_time - self._last_search_disable).total_seconds()
                if time_since_disable >= self.SEARCH_COOLDOWN_MINUTES * 60:
                    self._search_enabled = True
                    self._last_search_disable = None
                    self._search_requests.clear()
                    logger.info("Search grounding re-enabled after cooldown")
                    return True
                return False
            
            # Clean up old requests
            self._search_requests = [
                timestamp for timestamp in self._search_requests
                if (current_time - timestamp).total_seconds() < 60
            ]
            
            # Check if limit exceeded
            if len(self._search_requests) >= self.SEARCH_REQUESTS_PER_MINUTE:
                if self._search_enabled:
                    self._search_enabled = False
                    self._last_search_disable = current_time
                    logger.warning(
                        f"Search grounding disabled for {self.SEARCH_COOLDOWN_MINUTES} minutes "
                        f"due to rate limit ({self.SEARCH_REQUESTS_PER_MINUTE} requests/minute)"
                    )
                    # Notify about search disabling
                    await self._notify_state_change(
                        "search_disabled",
                        "Search grounding temporarily disabled due to rate limit",
                        {
                            "Search Requests": len(self._search_requests),
                            "Limit": self.SEARCH_REQUESTS_PER_MINUTE,
                            "Cooldown": f"{self.SEARCH_COOLDOWN_MINUTES} minutes"
                        }
                    )
                return False
            
            return True

    async def _get_current_config(self) -> genai.GenerationConfig:
        """Get the appropriate configuration based on search availability
        
        Returns:
            genai.GenerationConfig: Current configuration to use
        """
        if await self._check_search_rate_limit():
            return genai.GenerationConfig(
                temperature=0.9,
                top_p=1,
                top_k=40,
                max_output_tokens=self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
                tools=[self._search_tool]
            )
        return genai.GenerationConfig(
            temperature=0.9,
            top_p=1,
            top_k=40,
            max_output_tokens=self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS
        )

    async def _track_search_request(self) -> None:
        """Track a search request if search is enabled"""
        try:
            if self._search_enabled:
                async with self._search_lock:
                    self._search_requests.append(datetime.now())
        except Exception as e:
            logger.error(f"Failed to track search request: {e}")

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
        current_time = datetime.now()
        time_since_reset = current_time - self._last_reset
        hours_until_reset = max(0, 24 - int(time_since_reset.total_seconds() / 3600))
        
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