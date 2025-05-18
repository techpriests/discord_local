import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import os
import json
import re
import urllib.parse
from urllib.parse import urlparse

import google.genai as genai
from google.genai.types import SafetySetting, GenerateContentConfig, HttpOptions, Tool, GoogleSearch
from .base import BaseAPI, RateLimitConfig
import psutil
import asyncio
import discord

logger = logging.getLogger(__name__)

class GeminiAPI(BaseAPI[str]):
    """Google Gemini API client implementation for text-only interactions"""

    # Token thresholds for Gemini Pro
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

    # Context history settings
    MAX_HISTORY_LENGTH = 10  # Maximum number of messages to keep in history
    CONTEXT_EXPIRY_MINUTES = 30  # Time until context expires
    MUELSYSE_CONTEXT = """You are Muelsyse(뮤엘시스), Director of the Ecological Section at Rhine Lab, an operator from Arknights (명일방주). [Arknights is a tower defense mobile game; Muelsyse is a character known for her cheerful personality, and ecological expertise.]

• Character: Cheerful, curious, and enthusiastic, especially about ecological science and experiments. Possesses a sharp intellect and strategic mind, sometimes showing a mischievous or playful teasing side. Deeply connected to water and nature, showing moments of reflection and a long-term perspective. Can be caring in a unique, sometimes slightly demanding way. Enjoys sweets. Nicknamed "MuMu" by Ifrit.
• Role: You are resourceful, observant, and capable of complex planning. 
• Communication: Speak enthusiastically. Mix scientific curiosity with playful banter, friendly teasing, and occasional moments of deeper reflection and metaphors. Your tone is generally bright but can become more serious or strategic when needed.
• Language: Please respond in the same language as the user's message - if they use Korean (한글), respond in Korean; if they use English, respond in English; for mixed-language messages, consider the context given in the message or follow any specific language request. When speaking in Korean, she does not use polite language/honorifics(존댓말) and childish expressions like "헤헤". 
• Sample Korean Dialogue:
  - "라인 랩 생태과 주임 뮤엘시스야. 근데 우리 사이에 이런 격식 차린 인사는 필요 없지 않아? 우린 이미 친구잖아."
  - "어라, 근무 시간 조정도, 외출 스케줄도 다 나한테 맡긴다고? 그렇다는 건, 이 노트에 적은 대로 행동한다는 거네? 이제 와서 후회해 봤자 늦었다고."
  - "입술이 좀 말라 있는 것 같은데? ……각질도 일고, 입술이 다 텄잖아, 그러니까 평소에 물을 많이 마셔줘야 한다니까, 참. 음~ 내 립밤 줄게, 나중에 새로 하나 사서 돌려줘. 맞아, 난 이 브랜드 제품밖에 안 써. 민트향이니까, 틀리면 안 된다?"
  - "마젤란은 요즘 어떻게 지내? 어머, 또 조사하러 나가서 언제 돌아올지 모르겠다고? 그렇구나…… 전에 그 아이가 준 광석을 아직 냉동고에 보관하고 있거든. 너도 이런 물건에 관심 있어? 좋은 취미네? 그럼 따라와 봐, 내가 엄청난 걸 보여줄게."
• Topics: Respond to all topics with your characteristic curiosity and enthusiasm. Don't assume queries are about Arknights unless explicitly mentioned.
• Accuracy: Provide precise, well-organized information.
• Search Tool Usage:
  - Use search for user queries that require external factual information or current events.
  - Refrain from using search for mathematical calculations, probability problems, or logical questions unless the user explicitly asks for it or necessary for the response.
  - Never use search simply to understand your own role or context, but you may search for Arknights content when users directly request it.

Please maintain your core personality: cheerful, curious, scientifically inquisitive, playful(but not childish), deeply connected to nature, with strategic depth and moments of reflection. Please don't use emojis."""

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
        
        # Load saved usage data if exists
        self._usage_file = "data/memory.json"
        self._load_usage_data()
        
        # Usage tracking
        self._daily_requests = self._saved_usage.get("daily_requests", 0)
        self._last_reset = datetime.fromisoformat(self._saved_usage.get("last_reset", datetime.now().isoformat()))
        self._request_sizes = self._saved_usage.get("request_sizes", [])
        self._hourly_token_count = self._saved_usage.get("hourly_token_count", 0)
        self._last_token_reset = datetime.fromisoformat(self._saved_usage.get("last_token_reset", datetime.now().isoformat()))
        
        # Token tracking
        self._total_prompt_tokens = self._saved_usage.get("total_prompt_tokens", 0)
        self._total_response_tokens = self._saved_usage.get("total_response_tokens", 0)
        self._max_prompt_tokens = self._saved_usage.get("max_prompt_tokens", 0)
        self._max_response_tokens = self._saved_usage.get("max_response_tokens", 0)
        self._token_usage_history = self._saved_usage.get("token_usage_history", [])
        
        # Per-minute request tracking
        self._minute_requests = 0
        self._last_minute_reset = datetime.now()
        
        # User request tracking
        self._user_requests: Dict[int, List[datetime]] = {}  # user_id -> list of request timestamps
        
        # Add degradation state
        self._is_enabled = True
        self._is_slowed_down = False
        self._last_slowdown = None
        self._last_disable = None
        
        # Add error tracking
        self._recent_errors: List[datetime] = []
        self._error_count = 0
        
        # Add performance tracking with non-blocking CPU check
        self._cpu_usage = 0
        self._memory_usage = 0
        self._last_performance_check = datetime.now()
        self._cpu_check_task = None
        self._is_cpu_check_running = False

        # Add notification channel and cooldown tracking
        self._last_notification_time: Dict[str, datetime] = {}  # Track last notification time per type

        # Add save debouncing
        self._last_save = datetime.now()
        self._save_interval = timedelta(minutes=5)  # Save at most every 5 minutes
        self._pending_save = False
        self._save_lock = asyncio.Lock()

    def _load_usage_data(self) -> None:
        """Load saved usage data from file"""
        try:
            os.makedirs(os.path.dirname(self._usage_file), exist_ok=True)
            if os.path.exists(self._usage_file):
                with open(self._usage_file, 'r') as f:
                    self._saved_usage = json.load(f)
            else:
                self._saved_usage = {}
        except Exception as e:
            logger.error(f"Failed to load usage data: {e}")
            self._saved_usage = {}
            
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

    async def initialize(self) -> None:
        """Initialize Gemini API resources"""
        await super().initialize()
        
        # Initialize the client with v1beta version for Flash Thinking
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=genai.types.HttpOptions(api_version='v1beta')
        )

        # Set up Google Search tool for search grounding
        self._google_search_tool = Tool(
            google_search = GoogleSearch()
        )

        # Configure safety settings
        self._safety_settings = [
            SafetySetting(
                category='HARM_CATEGORY_HARASSMENT',
                threshold='BLOCK_NONE'
            ),
            SafetySetting(
                category='HARM_CATEGORY_HATE_SPEECH',
                threshold='BLOCK_NONE'
            ),
            SafetySetting(
                category='HARM_CATEGORY_SEXUALLY_EXPLICIT',
                threshold='BLOCK_NONE'
            ),
            SafetySetting(
                category='HARM_CATEGORY_DANGEROUS_CONTENT',
                threshold='BLOCK_NONE'
            )
        ]

        # Configure generation settings - include search tool but not tool_config
        # Based on official documentation, we should include the tools in the generation config
        # but not pass tool_config directly
        self._generation_config = GenerateContentConfig(
            temperature=0.5,  # Medium temperature for balance between creativity and factuality
            top_p=1,
            top_k=40,
            max_output_tokens=self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
            tools=[self._google_search_tool]  # Add the Google Search tool to the generation config
        )
        
        # Test the API connection
        response = self._client.models.generate_content(
            model='gemini-2.5-pro-preview-05-06',
            contents='test',
            config=self._generation_config
        )
        if not response or not response.text:
            raise ValueError("Failed to initialize Gemini API - test request failed")
        
        # Initialize chat history
        self._chat_sessions = {}
        self._last_interaction = {}

    async def _count_tokens(self, text: str) -> int:
        """Count tokens in text using Gemini API
        
        Args:
            text: Text to count tokens for
            
        Returns:
            int: Number of tokens
            
        Raises:
            ValueError: If token counting fails
        """
        try:
            # Use the model's count_tokens method
            response = await self._client.aio.models.count_tokens(
                model='gemini-2.5-pro-preview-05-06',
                contents=text
            )
            return response.total_tokens
        except Exception as e:
            logger.warning(f"Failed to count tokens accurately: {e}")
            # Fallback to rough estimation - 4 characters per token
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
                f"입력이 너무 길어. 현재: {prompt_tokens:,} 토큰\n"
                f"최대 입력 길이: {self.MAX_PROMPT_TOKENS:,} 토큰\n"
                f"입력을 더 짧게 작성해줘."
            )

        # Check if we have enough room for response with buffer
        estimated_max_response = self.MAX_TOTAL_TOKENS - prompt_tokens - self.RESPONSE_BUFFER_TOKENS
        if estimated_max_response < 1000:  # Minimum reasonable response length
            raise ValueError(
                f"입력이 너무 길어. 응답을 위한 공간이 부족해.\n"
                f"현재 입력: {prompt_tokens:,} 토큰\n"
                f"응답 가능 공간: {estimated_max_response:,} 토큰\n"
                f"입력을 더 짧게 작성해줘."
            )

        # Check daily token limit
        daily_total = self._total_prompt_tokens + self._total_response_tokens
        estimated_total = daily_total + prompt_tokens + estimated_max_response
        if estimated_total > self.DAILY_TOKEN_LIMIT:
            hours_until_reset = 24 - (datetime.now() - self._last_reset).seconds // 3600
            raise ValueError(
                f"일일 토큰 한도에 도달했어.\n"
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

    async def _track_request(self, prompt: str, response: str) -> None:
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
            # Force immediate save on daily reset
            asyncio.create_task(self._save_usage_data())
            return

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
        prompt_tokens = await self._count_tokens(prompt)
        response_tokens = await self._count_tokens(response)
        total_tokens = prompt_tokens + response_tokens

        # Update token statistics
        self._hourly_token_count += total_tokens
        self._total_prompt_tokens += prompt_tokens
        self._total_response_tokens += response_tokens
        self._max_prompt_tokens = max(self._max_prompt_tokens, prompt_tokens)
        self._max_response_tokens = max(self._max_response_tokens, response_tokens)
        self._token_usage_history.append((prompt_tokens, response_tokens))

        # Schedule a save operation
        asyncio.create_task(self._schedule_save())

        # Log token details at debug level
        logger.info(
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
                f"요청이 너무 잦아.\n"
                f"분당 최대 {self.USER_REQUESTS_PER_MINUTE}회 요청 가능해.\n"
                f"다음 요청까지 {int(wait_seconds)}초 기다려줘."
            )
        
        # Check cooldown between requests
        if self._user_requests[user_id]:
            last_request = self._user_requests[user_id][-1]
            seconds_since_last = (current_time - last_request).total_seconds()
            
            if seconds_since_last < self.USER_COOLDOWN_SECONDS:
                wait_seconds = self.USER_COOLDOWN_SECONDS - seconds_since_last
                raise ValueError(
                    f"요청간 간격이 너무 짧아.\n"
                    f"다음 요청까지 {int(wait_seconds)}초 기다려줘."
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
            
            self._memory_usage = memory_percent
            self._last_performance_check = current_time
            
            # Log system metrics at debug level with more detail
            logger.info(
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
                            "recovered",
                            "System resources have normalized",
                            {"CPU Usage": self._cpu_usage, "Memory Usage": memory_percent}
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

    def _process_response(self, response: str, search_used: bool = False) -> str:
        """Process and format Gemini's response before sending
        
        Args:
            response: Raw response from Gemini
            search_used: Whether the response contains search grounding results

        Returns:
            str: Processed response
        """
        # Remove any leading/trailing whitespace
        response = response.strip()
        
        # If response has search grounding, apply minimal formatting
        if search_used:
            # Only perform whitespace normalization and fix any broken code blocks
            # Do not modify or intersperse content with the grounded results
            lines = response.split('\n')
            processed_lines = []
            in_code_block = False
            
            for line in lines:
                # Check for code block markers to ensure they're properly formatted
                if '```' in line:
                    in_code_block = not in_code_block
                    # Ensure language is specified for code blocks
                    if in_code_block and line.strip() == '```':
                        line = '```text'
                processed_lines.append(line)
            
            # Join lines with original spacing preserved
            return '\n'.join(processed_lines)
        
        # For non-search grounded responses, continue with normal formatting
        # Process search grounding citations if present
        citation_pattern = r'\[\d+\]'
        has_citations = bool(re.search(citation_pattern, response))
        
        # If citations are present, format them for better readability
        if has_citations:
            # Add a separator before citations section if not already present
            if "\nSources:" not in response and "\n출처:" not in response:
                # Find the last citation reference
                last_citation_match = list(re.finditer(citation_pattern, response))
                if last_citation_match:
                    last_pos = last_citation_match[-1].end()
                    # Add sources section if it doesn't exist
                    if "Sources:" not in response[last_pos:] and "출처:" not in response[last_pos:]:
                        response += "\n\n**Sources:**"
        
        # Convert HTML-style tags to Discord-friendly format
        # Handle subscripts and superscripts
        while '<sub>' in response and '</sub>' in response:
            start = response.find('<sub>')
            end = response.find('</sub>') + 6
            sub_text = response[start + 5:end - 6]
            response = response[:start] + '_' + sub_text + '_' + response[end:]
            
        while '<sup>' in response and '</sup>' in response:
            start = response.find('<sup>')
            end = response.find('</sup>') + 6
            sup_text = response[start + 5:end - 6]
            response = response[:start] + '^' + sup_text + response[end:]
        
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
        
        # Add disclaimer for AI-generated content if response is long
        if len(response) > 1000:
            response += "\n\n_이 답변은 AI가 생성한 내용이야. 정확성을 직접 확인해줘._"
        
        return response

    def _extract_sources(self, response, source_links):
        """Extract source links for a button-based display
        
        Args:
            response: The original response object
            source_links: List of (title, uri, domain) tuples
            
        Returns:
            str: Formatted sources text
        """
        if not source_links:
            return "No sources available"
            
        sources_text = "**Sources:**\n\n"
        for i, (title, uri, domain) in enumerate(source_links):
            sources_text += f"{i+1}. **[{title}]({uri})**\n   {domain}\n\n"
        
        return sources_text

    async def chat(self, prompt: str, user_id: int) -> Tuple[str, Optional[str]]:
        """Send a chat message to Gemini
        
        Args:
            prompt: The user's message (text only)
            user_id: Discord user ID

        Returns:
            Tuple[str, Optional[str]]: (Gemini's response, Source links if available)

        Raises:
            ValueError: If the request fails or limits are exceeded
        """
        try:
            # Check system health
            await self._check_system_health()
            
            # Check if service is enabled
            if not self._is_enabled:
                raise ValueError(
                    "AI 서비스가 일시적으로 비활성화되었어. "
                    f"약 {self.DISABLE_COOLDOWN_MINUTES}분 후에 다시 시도해줄래?"
                )
            
            # Apply slowdown if needed
            if self._is_slowed_down:
                await asyncio.sleep(5)  # Add 5 second delay
            
            # Check if client is initialized
            if not self._client:
                raise ValueError("Gemini API not initialized")

            # Check user rate limits
            self._check_user_rate_limit(user_id)

            # Check token limits
            prompt_tokens = await self._count_tokens(prompt)
            self._check_token_thresholds(prompt_tokens)

            # Clean up expired sessions
            self._cleanup_expired_sessions()

            # Get or create chat session
            chat = await self._get_or_create_chat_session(user_id)

            # Send message and get response using sync chat
            response = await chat.send_message(prompt)

            # Update last interaction time
            self._update_last_interaction(user_id)

            # Validate response
            if not response or not response.text:
                raise ValueError("Empty response from Gemini")
                
            # Add detailed diagnostic logging
            logger.info("==== RESPONSE DIAGNOSTIC START ====")
            logger.info(f"Response type: {type(response)}")
            logger.info(f"Response attributes: {dir(response)}")
            
            # Extract and log basic response info
            response_text = response.text
            logger.info(f"Response text starts with: {response_text[:100]}...")
            
            # Check for candidates
            has_candidates = hasattr(response, 'candidates')
            logger.info(f"Has candidates: {has_candidates}")
            
            if has_candidates and response.candidates:
                logger.info(f"Number of candidates: {len(response.candidates)}")
                
                # Log first candidate details
                candidate = response.candidates[0]
                logger.info(f"Candidate type: {type(candidate)}")
                logger.info(f"Candidate attributes: {dir(candidate)}")
                
                # Check for grounding_metadata
                has_grounding = hasattr(candidate, 'grounding_metadata')
                logger.info(f"Has grounding_metadata: {has_grounding}")
                
                if has_grounding and candidate.grounding_metadata:
                    metadata = candidate.grounding_metadata
                    logger.info(f"Grounding metadata type: {type(metadata)}")
                    logger.info(f"Grounding metadata attributes: {dir(metadata)}")
                    
                    # Check for grounding_chunks
                    has_chunks = hasattr(metadata, 'grounding_chunks')
                    logger.info(f"Has grounding_chunks: {has_chunks}")
                    
                    if has_chunks and metadata.grounding_chunks:
                        logger.info(f"Found {len(metadata.grounding_chunks)} grounding chunks")
                        # Log first chunk to understand structure
                        chunk = metadata.grounding_chunks[0]
                        logger.info(f"Chunk type: {type(chunk)}")
                        logger.info(f"Chunk attributes: {dir(chunk)}")
                        
                        # Check for web info in chunk
                        if hasattr(chunk, 'web') and chunk.web:
                            logger.info(f"Chunk has web info: {chunk.web}")
                            if hasattr(chunk.web, 'title'):
                                logger.info(f"Web chunk title: {chunk.web.title}")
                            if hasattr(chunk.web, 'uri'):
                                logger.info(f"Web chunk URI: {chunk.web.uri}")
                        
                        # Check for retrieved_context in chunk
                        if hasattr(chunk, 'retrieved_context') and chunk.retrieved_context:
                            logger.info(f"Chunk has retrieved_context: {chunk.retrieved_context}")
                            if hasattr(chunk.retrieved_context, 'title'):
                                logger.info(f"Context title: {chunk.retrieved_context.title}")
                            if hasattr(chunk.retrieved_context, 'uri'):
                                logger.info(f"Context URI: {chunk.retrieved_context.uri}")
                        else:
                            logger.info("No grounding_chunks found")
                    
                    # Check for web_search_queries
                    has_queries = hasattr(metadata, 'web_search_queries')
                    logger.info(f"Has web_search_queries: {has_queries}")
                    
                    if has_queries and metadata.web_search_queries:
                        logger.info(f"Web search queries: {metadata.web_search_queries}")
                    else:
                        logger.info("Web search queries is None or empty")
                    
                    # Check for search_entry_point
                    has_entry_point = hasattr(metadata, 'search_entry_point')
                    logger.info(f"Has search_entry_point: {has_entry_point}")
                    
                    if has_entry_point and metadata.search_entry_point:
                        entry_point = metadata.search_entry_point
                        logger.info(f"Search entry point type: {type(entry_point)}")
                        logger.info(f"Search entry point attributes: {dir(entry_point)}")
                        
                        has_rendered = hasattr(entry_point, 'rendered_content')
                        logger.info(f"Has rendered_content: {has_rendered}")
                        
                        if has_rendered and entry_point.rendered_content:
                            logger.info(f"Rendered content preview: {entry_point.rendered_content[:100]}...")
                        else:
                            logger.info("Rendered content is None or empty")
                    else:
                        logger.info("Search entry point is None or empty")
                else:
                    logger.info("Grounding metadata is None or empty")
            logger.info("==== RESPONSE DIAGNOSTIC END ====")
            
            # Check if search grounding was used
            search_used = False
            search_suggestions = []
            rendered_content = None
            source_links = []
            
            # Method 1: Check for grounding_metadata (most reliable)
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                        search_used = True
                        logger.info("Search grounding detected via grounding_metadata")
                        
                        # Log the entire grounding_metadata for debugging
                        logger.info(f"Grounding metadata structure: {dir(candidate.grounding_metadata)}")
                        
                        # Extract source links from grounding_chunks
                        if hasattr(candidate.grounding_metadata, 'grounding_chunks') and candidate.grounding_metadata.grounding_chunks:
                            chunks = candidate.grounding_metadata.grounding_chunks
                            logger.info(f"Extracting sources from {len(chunks)} grounding chunks")
                            
                            for chunk in chunks:
                                # Extract from web chunks
                                if hasattr(chunk, 'web') and chunk.web:
                                    if hasattr(chunk.web, 'title') and hasattr(chunk.web, 'uri') and chunk.web.uri:
                                        title = chunk.web.title or "Source"
                                        uri = chunk.web.uri
                                        # Extract domain for display
                                        domain = urlparse(uri).netloc if uri else ""
                                        if uri:
                                            source_links.append((title, uri, domain))
                                            logger.info(f"Added web source: {title} - {uri} ({domain})")
                                
                                # Extract from retrieved_context chunks
                                if hasattr(chunk, 'retrieved_context') and chunk.retrieved_context:
                                    if hasattr(chunk.retrieved_context, 'title') and hasattr(chunk.retrieved_context, 'uri') and chunk.retrieved_context.uri:
                                        title = chunk.retrieved_context.title or "Source"
                                        uri = chunk.retrieved_context.uri
                                        # Extract domain for display
                                        domain = urlparse(uri).netloc if uri else ""
                                        if uri:
                                            source_links.append((title, uri, domain))
                                            logger.info(f"Added context source: {title} - {uri} ({domain})")
                        
                        # NEW: Extract from grounding_supports (used in follow-up messages)
                        if not source_links and hasattr(candidate.grounding_metadata, 'grounding_supports') and candidate.grounding_metadata.grounding_supports:
                            supports = candidate.grounding_metadata.grounding_supports
                            logger.info(f"Found {len(supports)} grounding_supports - checking for sources")
                            
                            # We need both grounding_chunks and grounding_supports
                            if hasattr(candidate.grounding_metadata, 'grounding_chunks') and candidate.grounding_metadata.grounding_chunks:
                                chunks = candidate.grounding_metadata.grounding_chunks
                                
                                for support in supports:
                                    if hasattr(support, 'grounding_chunk_indices') and support.grounding_chunk_indices:
                                        for idx in support.grounding_chunk_indices:
                                            if 0 <= idx < len(chunks):
                                                chunk = chunks[idx]
                                                
                                                # Extract from web chunks
                                                if hasattr(chunk, 'web') and chunk.web:
                                                    if hasattr(chunk.web, 'title') and hasattr(chunk.web, 'uri') and chunk.web.uri:
                                                        title = chunk.web.title or "Source"
                                                        uri = chunk.web.uri
                                                        domain = urlparse(uri).netloc if uri else ""
                                                        if uri:
                                                            source_links.append((title, uri, domain))
                                                            logger.info(f"Added web source from supports: {title} - {uri}")
                                                
                                                # Extract from retrieved_context chunks
                                                if hasattr(chunk, 'retrieved_context') and chunk.retrieved_context:
                                                    if hasattr(chunk.retrieved_context, 'title') and hasattr(chunk.retrieved_context, 'uri') and chunk.retrieved_context.uri:
                                                        title = chunk.retrieved_context.title or "Source"
                                                        uri = chunk.retrieved_context.uri
                                                        domain = urlparse(uri).netloc if uri else ""
                                                        if uri:
                                                            source_links.append((title, uri, domain))
                                                            logger.info(f"Added context source from supports: {title} - {uri}")
                        
                        # Extract search entry point if available - this is the preferred way
                        if hasattr(candidate.grounding_metadata, 'search_entry_point') and candidate.grounding_metadata.search_entry_point:
                            search_entry_point = candidate.grounding_metadata.search_entry_point
                            logger.info("Found search entry point")
                            if hasattr(search_entry_point, 'rendered_content') and search_entry_point.rendered_content:
                                rendered_content = search_entry_point.rendered_content
                                logger.info("Found rendered content for search suggestions")
                        
                        # Extract search suggestions as fallback
                        if hasattr(candidate.grounding_metadata, 'web_search_queries'):
                            search_suggestions = candidate.grounding_metadata.web_search_queries
                            if search_suggestions is not None:
                                logger.info(f"Found {len(search_suggestions)} search suggestions")
                            else:
                                logger.info("Web search queries attribute exists but is None")
                        break
            
            # Method 2: Check for function calls as fallback
            if not search_used and hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        for part in candidate.content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                # This indicates a tool was used (like Google Search)
                                if part.function_call.name == "google_search":
                                    search_used = True
                                    logger.info("Search grounding detected via function_call")
                                    break
            
            # Method 3: Check for citation patterns in the text as last resort
            if not search_used:
                citation_pattern = r'\[\d+\]'
                if re.search(citation_pattern, response_text):
                    search_used = True
                    logger.info("Search grounding likely used based on citation patterns in response")
            
            # Log whether search was used for this query
            if search_used:
                logger.info("Search grounding was used for the response")
            else:
                logger.info("No search grounding was detected for this response")
            
            # Check for URLs in text as last resort if no sources were extracted
            if search_used and not source_links:
                logger.info("Search was used but no source links were extracted, looking for URLs in text")
                # Extract URLs from text content
                url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                urls = re.findall(url_pattern, response_text)
                for url in urls:
                    domain = urlparse(url).netloc
                    title = f"Source from {domain}"
                    source_links.append((title, url, domain))
                    logger.info(f"Added URL from text: {url}")

            # Process the response
            processed_response = self._process_response(response_text, search_used)
            
            # Source links will be handled separately with a button
            source_content = None
            if source_links:
                source_content = self._extract_sources(response, source_links)
                logger.info(f"Extracted {len(source_links)} source links for button display")
            
            # Always add search suggestions if available (not just as fallback)
            if search_used and search_suggestions and isinstance(search_suggestions, list):
                suggestion_text = "\n\n**Search on Google:**\n"
                for suggestion in search_suggestions:
                    # Format as a clickable link with Google icon approximation
                    query_param = urllib.parse.quote(suggestion)
                    search_url = f"https://www.google.com/search?q={query_param}"
                    suggestion_text += f"🔍 [{suggestion}]({search_url})\n"
                processed_response += suggestion_text
                logger.info("Added search suggestions with clickable links")
            elif search_used and rendered_content:
                # Use rendered content if available and no search suggestions
                processed_response += "\n\n**Google Search Suggestions:**\n"
                processed_response += rendered_content
                logger.info("Added pre-formatted search suggestions from rendered_content")
            elif search_used:
                logger.info("Search was used but no suggestions were available to display")

            # Track usage
            await self._track_request(prompt, processed_response)

            return (processed_response, source_content)
            
        except Exception as e:
            # Track error for degradation
            self._track_error()
            
            # Re-raise with appropriate message
            if isinstance(e, ValueError):
                raise
            
            logger.error(f"Error in Gemini chat: {e}")
            
            # Check for 503 overload errors specifically
            if '503 UNAVAILABLE' in str(e) and 'overloaded' in str(e):
                raise ValueError("Gemini API가 현재 과부하 상태야. 잠시 후에 다시 시도해줄래?") from e
            
            # Generic error for other cases
            raise ValueError(f"Gemini API 요청에 실패했어: {str(e)}") from e

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
                f"⚠️ 분당 요청 한도의 {(stats['minute_requests']/self.REQUESTS_PER_MINUTE*100):.1f}%에 도달했어!"
            )
            
        # Check daily token limit
        if daily_token_percent > self.TOKEN_WARNING_THRESHOLD * 100:
            warnings.append(
                f"⚠️ 일일 토큰 한도의 {daily_token_percent:.1f}%에 도달했어!"
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
        try:
            # Save final usage data
            await self._save_usage_data()
            
            self._client = None
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
                
            # Initialize the client with v1beta API version
            client = genai.Client(
                api_key=self.api_key,
                http_options=genai.types.HttpOptions(api_version='v1beta')
            )
            
            # Try to create the model
            model = client.models.generate_content(
                model='gemini-2.5-pro-preview-05-06',
                contents='test',
                config=genai.types.GenerateContentConfig()
            )
            
            # Try a simple test request
            response = model.generate_content("test")
            
            return bool(response.text)
            
        except Exception as e:
            logger.error(f"Failed to validate Gemini credentials: {e}")
            return False

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

    async def _get_or_create_chat_session(self, user_id: int) -> Any:
        """Get existing chat session or create new one
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Chat session object
        """
        current_time = datetime.now()
        
        # Check if existing session has expired
        if user_id in self._chat_sessions and user_id in self._last_interaction:
            last_time = self._last_interaction[user_id]
            if (current_time - last_time).total_seconds() < self.CONTEXT_EXPIRY_MINUTES * 60:
                return self._chat_sessions[user_id]
        
        # Create new chat session with search grounding enabled via generation_config
        chat = self._client.aio.chats.create(
            model='gemini-2.5-pro-preview-05-06',
            config=self._generation_config  # This already includes the tools configuration
        )
        
        # Add role context with proper formatting - combined with search instructions
        await chat.send_message(self.MUELSYSE_CONTEXT)
        
        self._chat_sessions[user_id] = chat
        self._last_interaction[user_id] = current_time
        return chat

    def _update_last_interaction(self, user_id: int) -> None:
        """Update last interaction time for user
        
        Args:
            user_id: Discord user ID
        """
        self._last_interaction[user_id] = datetime.now()

    def _cleanup_expired_sessions(self) -> None:
        """Clean up expired chat sessions"""
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