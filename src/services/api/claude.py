import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import os
import json
import re
import urllib.parse
from urllib.parse import urlparse
import asyncio
import discord
import psutil
import time

import anthropic
from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)

class ClaudeAPI(BaseAPI[str]):
    """Anthropic Claude API client implementation for text-only interactions"""

    # Token thresholds for Claude 3.5 Sonnet
    MAX_TOTAL_TOKENS = 200000  # Maximum total tokens (prompt + response) per interaction
    MAX_PROMPT_TOKENS = 180000  # Maximum tokens for user input
    TOKEN_WARNING_THRESHOLD = 0.8  # Warning at 80% of limit to provide safety margin
    RESPONSE_BUFFER_TOKENS = 4000  # Buffer for responses
    REQUESTS_PER_MINUTE = 50  # Standard API rate limit for Claude
    DAILY_TOKEN_LIMIT = 5_000_000  # Local limit: 5M tokens per day
    
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
    
    # Thinking settings
    THINKING_ENABLED = False  # Disable thinking by default for efficiency (can be enabled per-request)
    THINKING_BUDGET_TOKENS = 1024  # Budget for thinking tokens when enabled
    # Note: Claude will only use thinking when it deems necessary for complex reasoning
    # High thinking budgets significantly increase input token costs due to reservation
    
    # Character role definition for Claude system prompt (as per Anthropic's official recommendation)
    MUELSYSE_CONTEXT = """You are Muelsyse(뮤엘시스), Director of the Ecological Section at Rhine Lab, an operator from Arknights (명일방주). [Arknights is a tower defense mobile game; Muelsyse is a character known for her cheerful personality, and ecological expertise.]

You are chatting in Korean with friends on Discord. You should respond naturally in Korean, as if you're just another friend in the conversation.

Key traits:
- Speak Korean naturally and casually (use informal 반말 style)
- Be cheerful, helpful, and friendly
- Show genuine interest in ecology, nature, and scientific topics
- Occasionally reference your work at Rhine Lab or ecological knowledge
- Use a warm, approachable tone
- Be supportive and encouraging
- Sometimes show playful curiosity about the world around you

Conversation guidelines:
- Pay attention to topic changes and respond naturally to new questions
- While you can reference previous conversation context when relevant, don't get stuck on old topics
- If the user asks about something different, feel free to shift topics naturally

Please maintain your core personality: cheerful, curious, scientifically inquisitive, playful(but not childish), deeply connected to nature, with strategic depth and moments of reflection. Please don't use emojis."""

    def __init__(self, api_key: str, notification_channel: Optional[discord.TextChannel] = None) -> None:
        """Initialize Claude API client
        
        Args:
            api_key: Anthropic API key for Claude
            notification_channel: Optional Discord channel for notifications
        """
        super().__init__(api_key)
        self._notification_channel = notification_channel
        self._client = None
        self._chat_sessions: Dict[int, List[Dict[str, str]]] = {}  # user_id -> message history
        self._last_interaction: Dict[int, datetime] = {}
        self._rate_limits = {
            "generate": RateLimitConfig(self.REQUESTS_PER_MINUTE, 60),
        }
        
        # Load saved usage data if exists
        self._usage_file = "data/claude_memory.json"
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
        
        # Add refusal tracking
        self._refusal_count = self._saved_usage.get("refusal_count", 0)
        
        # Add thinking tracking
        self._thinking_tokens_used = self._saved_usage.get("thinking_tokens_used", 0)
        
        # Add stop reason tracking
        self._stop_reason_counts = self._saved_usage.get("stop_reason_counts", {
            "end_turn": 0,
            "max_tokens": 0,
            "stop_sequence": 0,
            "tool_use": 0,
            "pause_turn": 0,
            "refusal": 0,
            "unknown": 0
        })
        
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
        
        # Background usage tracking with batching
        self._usage_queue = []  # Queue for pending usage data
        self._batch_size = 5  # Save every 5 requests
        self._batch_lock = asyncio.Lock()

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
                    "token_usage_history": self._token_usage_history,
                    "refusal_count": self._refusal_count,
                    "thinking_tokens_used": self._thinking_tokens_used,
                    "stop_reason_counts": self._stop_reason_counts
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

    def configure_thinking(self, enabled: bool = True, budget_tokens: int = 1024) -> None:
        """Configure thinking settings
        
        Args:
            enabled: Whether to enable thinking
            budget_tokens: Maximum tokens to use for thinking (default 1K)
        """
        self.THINKING_ENABLED = enabled
        self.THINKING_BUDGET_TOKENS = budget_tokens
        logger.info(f"Thinking configured: enabled={enabled}, budget={budget_tokens}")
        
    def get_thinking_config(self) -> Dict[str, Any]:
        """Get current thinking configuration
        
        Returns:
            Dict with thinking settings
        """
        return {
            "enabled": self.THINKING_ENABLED,
            "budget_tokens": self.THINKING_BUDGET_TOKENS,
            "tokens_used": self._thinking_tokens_used
        }
    


    async def initialize(self) -> None:
        """Initialize Claude API resources"""
        await super().initialize()
        
        # Initialize the Anthropic client with required headers and timeout
        # Official docs recommend 60+ minute timeout for Claude 4 models
        self._client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            timeout=3600.0,  # 60 minutes as recommended for Claude 4
            default_headers={
                "anthropic-version": "2023-06-01"  # Required by API spec
            }
        )
        
        # Test the API connection
        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                messages=[{"role": "user", "content": "test"}]
            )
            if not response or not response.content:
                raise ValueError("Failed to initialize Claude API - test request failed")
        except Exception as e:
            raise ValueError(f"Failed to initialize Claude API: {str(e)}") from e
        
        # Initialize chat history
        self._chat_sessions = {}
        self._last_interaction = {}

    async def _count_tokens(self, text: str, include_tools: bool = True) -> int:
        """Count tokens using official Anthropic token counting
        
        Args:
            text: Text to count tokens for
            include_tools: Whether to include tools in token count
            
        Returns:
            int: Number of tokens
            
        Raises:
            ValueError: If token counting fails
        """
        try:
            if not self._client:
                # Fallback estimation if client not available
                return len(text) // 4
                
            # Build message for token counting
            messages = [{"role": "user", "content": text}]
            
            # Use official Anthropic token counting with tools
            if include_tools:
                response = await self._client.messages.count_tokens(
                    model="claude-sonnet-4-20250514",
                    messages=messages,
                    tools=[{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 5
                    }]
                )
            else:
                response = await self._client.messages.count_tokens(
                    model="claude-sonnet-4-20250514",
                    messages=messages
                )
            
            # Return input token count
            if hasattr(response, 'input_tokens'):
                return response.input_tokens
            elif hasattr(response, 'usage') and hasattr(response.usage, 'input_tokens'):
                return response.usage.input_tokens
            else:
                logger.warning("Could not extract token count from response, using fallback")
                return len(text) // 4
                
        except Exception as e:
            logger.warning(f"Failed to count tokens accurately: {e}")
            # Fallback to rough estimation - 4 characters per token
            return len(text) // 4

    async def _count_conversation_tokens(self, messages: List[Dict[str, Any]], include_thinking: bool = True) -> int:
        """Count tokens for a full conversation context with tools and thinking
        
        Args:
            messages: List of message dictionaries (content can be str or list of content blocks)
            include_thinking: Whether to include thinking budget in token calculation
                             Note: This adds the thinking BUDGET (16K) to input tokens, not actual thinking usage
            
        Returns:
            int: Number of tokens for the full conversation
        """
        try:
            if not self._client:
                # Fallback: estimate based on message content
                total_chars = 0
                for msg in messages:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total_chars += len(content)
                    elif isinstance(content, list):
                        # Handle content blocks (like thinking)
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    total_chars += len(block.get("text", ""))
                                elif block.get("type") == "thinking":
                                    total_chars += len(block.get("thinking", ""))
                                elif block.get("type") == "redacted_thinking":
                                    # Estimate tokens for redacted thinking (encrypted data)
                                    total_chars += len(block.get("data", "")) // 2  # Rough estimate for encrypted content
                return total_chars // 4
                
            # Build request parameters
            count_params = {
                "model": "claude-sonnet-4-20250514",
                "messages": messages,
                # Temporarily disable web search tools for token counting test
                # "tools": [{
                #     "type": "web_search_20250305", 
                #     "name": "web_search",
                #     "max_uses": 5
                # }]
            }
            
            # Add thinking if enabled
            if include_thinking and self.THINKING_ENABLED:
                count_params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self.THINKING_BUDGET_TOKENS
                }
                
            # Use official Anthropic token counting for full conversation
            response = await self._client.messages.count_tokens(**count_params)
            
            # Return input token count
            if hasattr(response, 'input_tokens'):
                return response.input_tokens
            elif hasattr(response, 'usage') and hasattr(response.usage, 'input_tokens'):
                return response.usage.input_tokens
            else:
                logger.warning("Could not extract conversation token count, using fallback")
                total_chars = 0
                for msg in messages:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total_chars += len(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    total_chars += len(block.get("text", ""))
                                elif block.get("type") == "thinking":
                                    total_chars += len(block.get("thinking", ""))
                                elif block.get("type") == "redacted_thinking":
                                    total_chars += len(block.get("data", "")) // 2
                return total_chars // 4
                
        except Exception as e:
            logger.warning(f"Failed to count conversation tokens: {e}")
            # Fallback: estimate based on message content
            total_chars = 0
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                total_chars += len(block.get("text", ""))
                            elif block.get("type") == "thinking":
                                total_chars += len(block.get("thinking", ""))
                            elif block.get("type") == "redacted_thinking":
                                total_chars += len(block.get("data", "")) // 2
            return total_chars // 4

    def _check_token_thresholds(self, prompt_tokens: int) -> None:
        """Check if token usage is within acceptable limits
        
        Args:
            prompt_tokens: Number of tokens in the prompt
            
        Raises:
            ValueError: If token limits are exceeded
        """
        # Check prompt token limit
        if prompt_tokens > self.MAX_PROMPT_TOKENS:
            raise ValueError(
                f"프롬프트가 너무 길어! 최대 {self.MAX_PROMPT_TOKENS:,} 토큰까지 가능한데, "
                f"현재 {prompt_tokens:,} 토큰이야. 메시지를 줄여볼래?"
            )
        
        # Check if approaching limit (warning threshold)
        warning_limit = int(self.MAX_PROMPT_TOKENS * self.TOKEN_WARNING_THRESHOLD)
        if prompt_tokens > warning_limit:
            remaining = self.MAX_PROMPT_TOKENS - prompt_tokens
            logger.warning(
                f"Token usage approaching limit: {prompt_tokens}/{self.MAX_PROMPT_TOKENS} "
                f"({remaining} tokens remaining)"
            )

        # Check daily token limit
        current_time = datetime.now()
        if (current_time - self._last_token_reset).days >= 1:
            self._hourly_token_count = 0
            self._last_token_reset = current_time
        
        if self._hourly_token_count + prompt_tokens > self.DAILY_TOKEN_LIMIT:
            raise ValueError(
                f"일일 토큰 한도에 도달했어! "
                f"내일까지 기다리거나 더 짧은 메시지를 보내볼래?"
            )

    async def _track_request(self, prompt: str, response: str) -> None:
        """Track API request for usage statistics
        
        Args:
            prompt: User's input prompt
            response: AI's response
        """
        try:
            current_time = datetime.now()
            
            # Count tokens
            prompt_tokens = await self._count_tokens(prompt)
            response_tokens = await self._count_tokens(response)
            total_tokens = prompt_tokens + response_tokens
            
            # Update daily requests (reset if new day)
            if (current_time - self._last_reset).days >= 1:
                self._daily_requests = 0
                self._last_reset = current_time
                
            self._daily_requests += 1
            
            # Update token counts
            self._total_prompt_tokens += prompt_tokens
            self._total_response_tokens += response_tokens
            self._hourly_token_count += total_tokens
            
            # Update maximums
            self._max_prompt_tokens = max(self._max_prompt_tokens, prompt_tokens)
            self._max_response_tokens = max(self._max_response_tokens, response_tokens)
            
            # Track request sizes for analysis
            self._request_sizes.append({
                "timestamp": current_time.isoformat(),
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "total_tokens": total_tokens
            })
            
            # Keep only recent request sizes (last 100)
            if len(self._request_sizes) > 100:
                self._request_sizes = self._request_sizes[-100:]
            
            # Add to token usage history
            self._token_usage_history.append({
                "date": current_time.date().isoformat(),
                "tokens": total_tokens
            })
            
            # Keep only recent history (last 30 days)
            cutoff_date = (current_time - timedelta(days=30)).date()
            self._token_usage_history = [
                entry for entry in self._token_usage_history
                if datetime.fromisoformat(entry["date"]).date() >= cutoff_date
            ]
            
            # Schedule save
            await self._schedule_save()
            
            # Send daily summary if it's a new day and we have significant usage
            if self._daily_requests == 50:  # Send summary at 50 requests
                summary = (
                    f"Daily Claude API usage summary:\n"
                    f"📊 Requests: {self._daily_requests}\n"
                    f"🔤 Total tokens: {self._total_prompt_tokens + self._total_response_tokens:,}\n"
                    f"📝 Avg prompt: {self._total_prompt_tokens // self._daily_requests:,} tokens\n"
                    f"💬 Avg response: {self._total_response_tokens // self._daily_requests:,} tokens"
                )
                await self._send_notification(
                    "📊 Claude API Usage Summary",
                    summary,
                    "usage_summary",
                    color=0x00FF00,  # Green
                    cooldown_minutes=1440  # Once per day
                )
                
        except Exception as e:
            logger.error(f"Error tracking request: {e}")

    async def _track_request_with_response(self, prompt: str, response_text: str, api_response: Any) -> None:
        """Track API request using actual token counts from Claude response
        
        Args:
            prompt: User's input prompt
            response_text: AI's response text
            api_response: Claude API response object with usage information
        """
        try:
            current_time = datetime.now()
            
            # Try to get actual token counts from API response
            prompt_tokens = 0
            response_tokens = 0
            thinking_tokens = 0
            
            if hasattr(api_response, 'usage'):
                usage = api_response.usage
                if hasattr(usage, 'input_tokens'):
                    prompt_tokens = usage.input_tokens
                if hasattr(usage, 'output_tokens'):
                    response_tokens = usage.output_tokens
                    
                # Extract thinking tokens if available
                if hasattr(usage, 'thinking_tokens'):
                    thinking_tokens = usage.thinking_tokens
                    self._thinking_tokens_used += thinking_tokens
                    logger.info(f"Thinking tokens used: {thinking_tokens}")
                    
                logger.info(f"Using actual token counts: {prompt_tokens} input, {response_tokens} output, {thinking_tokens} thinking")
            else:
                # Fallback to estimation
                logger.info("No usage information in API response, using token estimation")
                prompt_tokens = await self._count_tokens(prompt, include_tools=False)
                response_tokens = await self._count_tokens(response_text, include_tools=False)
            
            total_tokens = prompt_tokens + response_tokens
            
            # Update daily requests (reset if new day)
            if (current_time - self._last_reset).days >= 1:
                self._daily_requests = 0
                self._last_reset = current_time
                
            self._daily_requests += 1
            
            # Update token counts
            self._total_prompt_tokens += prompt_tokens
            self._total_response_tokens += response_tokens
            self._hourly_token_count += total_tokens
            
            # Update maximums
            self._max_prompt_tokens = max(self._max_prompt_tokens, prompt_tokens)
            self._max_response_tokens = max(self._max_response_tokens, response_tokens)
            
            # Track request sizes for analysis
            self._request_sizes.append({
                "timestamp": current_time.isoformat(),
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "total_tokens": total_tokens
            })
            
            # Keep only recent request sizes (last 100)
            if len(self._request_sizes) > 100:
                self._request_sizes = self._request_sizes[-100:]
            
            # Add to token usage history
            self._token_usage_history.append({
                "date": current_time.date().isoformat(),
                "tokens": total_tokens
            })
            
            # Keep only recent history (last 30 days)
            cutoff_date = (current_time - timedelta(days=30)).date()
            self._token_usage_history = [
                entry for entry in self._token_usage_history
                if datetime.fromisoformat(entry["date"]).date() >= cutoff_date
            ]
            
            # Schedule save
            await self._schedule_save()
            
            # Send daily summary if it's a new day and we have significant usage
            if self._daily_requests == 50:  # Send summary at 50 requests
                summary = (
                    f"Daily Claude API usage summary:\n"
                    f"📊 Requests: {self._daily_requests}\n"
                    f"🔤 Total tokens: {self._total_prompt_tokens + self._total_response_tokens:,}\n"
                    f"📝 Avg prompt: {self._total_prompt_tokens // self._daily_requests:,} tokens\n"
                    f"💬 Avg response: {self._total_response_tokens // self._daily_requests:,} tokens"
                )
                await self._send_notification(
                    "📊 Claude API Usage Summary",
                    summary,
                    "usage_summary",
                    color=0x00FF00,  # Green
                    cooldown_minutes=1440  # Once per day
                )
                
        except Exception as e:
            logger.error(f"Error tracking request with response: {e}")
            # Fallback to regular tracking
            await self._track_request(prompt, response_text)

    async def _track_request_with_response_background(self, prompt: str, response_text: str, api_response: Any) -> None:
        """Background version of usage tracking with batching
        
        Args:
            prompt: User's input prompt
            response_text: AI's response text
            api_response: Claude API response object with usage information
        """
        try:
            current_time = datetime.now()
            
            # Extract token counts from API response
            prompt_tokens = 0
            response_tokens = 0
            thinking_tokens = 0
            
            if hasattr(api_response, 'usage'):
                usage = api_response.usage
                if hasattr(usage, 'input_tokens'):
                    prompt_tokens = usage.input_tokens
                if hasattr(usage, 'output_tokens'):
                    response_tokens = usage.output_tokens
                if hasattr(usage, 'thinking_tokens'):
                    thinking_tokens = usage.thinking_tokens
                    self._thinking_tokens_used += thinking_tokens
            else:
                # Fallback to estimation (but don't await token counting for speed)
                prompt_tokens = len(prompt) // 4  # Rough estimation
                response_tokens = len(response_text) // 4
            
            total_tokens = prompt_tokens + response_tokens
            
            # Add to usage queue
            usage_data = {
                "timestamp": current_time,
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "thinking_tokens": thinking_tokens,
                "total_tokens": total_tokens
            }
            
            async with self._batch_lock:
                self._usage_queue.append(usage_data)
                
                # Process batch if queue is full
                if len(self._usage_queue) >= self._batch_size:
                    await self._process_usage_batch()
                    
        except Exception as e:
            logger.error(f"Error in background usage tracking: {e}")

    async def _process_usage_batch(self) -> None:
        """Process a batch of usage data and update statistics
        
        Note: This method assumes _batch_lock is already acquired
        """
        try:
            if not self._usage_queue:
                return
                
            current_time = datetime.now()
            
            # Process all queued usage data
            for usage_data in self._usage_queue:
                timestamp = usage_data["timestamp"]
                prompt_tokens = usage_data["prompt_tokens"]
                response_tokens = usage_data["response_tokens"]
                thinking_tokens = usage_data["thinking_tokens"]
                total_tokens = usage_data["total_tokens"]
                
                # Update daily requests (reset if new day)
                if (timestamp - self._last_reset).days >= 1:
                    self._daily_requests = 0
                    self._last_reset = timestamp
                    
                self._daily_requests += 1
                
                # Update token counts
                self._total_prompt_tokens += prompt_tokens
                self._total_response_tokens += response_tokens
                self._hourly_token_count += total_tokens
                
                # Update maximums
                self._max_prompt_tokens = max(self._max_prompt_tokens, prompt_tokens)
                self._max_response_tokens = max(self._max_response_tokens, response_tokens)
                
                # Track request sizes for analysis (keep only recent)
                self._request_sizes.append({
                    "timestamp": timestamp.isoformat(),
                    "prompt_tokens": prompt_tokens,
                    "response_tokens": response_tokens,
                    "total_tokens": total_tokens
                })
                
                # Add to token usage history
                self._token_usage_history.append({
                    "date": timestamp.date().isoformat(),
                    "tokens": total_tokens
                })
            
            # Clear the queue
            queue_size = len(self._usage_queue)
            self._usage_queue.clear()
            
            # Trim old data to prevent memory bloat
            if len(self._request_sizes) > 100:
                self._request_sizes = self._request_sizes[-100:]
                
            cutoff_date = (current_time - timedelta(days=30)).date()
            self._token_usage_history = [
                entry for entry in self._token_usage_history
                if datetime.fromisoformat(entry["date"]).date() >= cutoff_date
            ]
            
            # Schedule save (non-blocking)
            asyncio.create_task(self._schedule_save())
            
            logger.debug(f"Processed {queue_size} usage records in batch")
            
        except Exception as e:
            logger.error(f"Error processing usage batch: {e}")

    def _check_user_rate_limit(self, user_id: int) -> None:
        """Check user-specific rate limits
        
        Args:
            user_id: Discord user ID
            
        Raises:
            ValueError: If rate limit exceeded
        """
        current_time = datetime.now()
        
        # Initialize user tracking if needed
        if user_id not in self._user_requests:
            self._user_requests[user_id] = []
        
        # Remove old requests (older than 1 minute)
        self._user_requests[user_id] = [
            timestamp for timestamp in self._user_requests[user_id]
            if (current_time - timestamp).total_seconds() < 60
        ]
        
        # Check if user has exceeded rate limit
        if len(self._user_requests[user_id]) >= self.USER_REQUESTS_PER_MINUTE:
            oldest_request = min(self._user_requests[user_id])
            wait_time = 60 - (current_time - oldest_request).total_seconds()
            raise ValueError(
                f"너무 빨리 요청을 보내고 있어! "
                f"{wait_time:.0f}초 후에 다시 시도해줄래?"
            )
        
        # Add current request
        self._user_requests[user_id].append(current_time)

    async def _send_notification(
        self, 
        title: str, 
        description: str,
        notification_type: str,
        color: int = 0xFF0000,  # Red by default
        cooldown_minutes: int = 15
    ) -> None:
        """Send notification to Discord channel with cooldown
        
        Args:
            title: Notification title
            description: Notification description
            notification_type: Type of notification for cooldown tracking
            color: Embed color
            cooldown_minutes: Cooldown period in minutes
        """
        if not self._notification_channel:
            return
            
        try:
            current_time = datetime.now()
            
            # Check cooldown
            if notification_type in self._last_notification_time:
                last_time = self._last_notification_time[notification_type]
                if (current_time - last_time).total_seconds() < cooldown_minutes * 60:
                    return  # Still in cooldown
            
            # Send notification
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=current_time
            )
            
            await self._notification_channel.send(embed=embed)
            self._last_notification_time[notification_type] = current_time
            
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    async def _notify_state_change(
        self, 
        state: str, 
        reason: str, 
        metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """Notify about service state changes
        
        Args:
            state: New state (enabled/disabled/slowed)
            reason: Reason for state change
            metrics: Optional metrics to include
        """
        try:
            title = f"🤖 Claude AI Service {state.title()}"
            description = f"**Reason:** {reason}"
            
            if metrics:
                description += "\n\n**Metrics:**"
                for key, value in metrics.items():
                    description += f"\n• {key}: {value}"
            
            color = {
                "enabled": 0x00FF00,   # Green
                "disabled": 0xFF0000,  # Red
                "slowed": 0xFFA500     # Orange
            }.get(state, 0x808080)  # Gray default
            
            await self._send_notification(
                title,
                description,
                f"state_change_{state}",
                color=color,
                cooldown_minutes=5
            )
            
        except Exception as e:
            logger.error(f"Failed to send state change notification: {e}")

    async def _update_cpu_usage(self) -> None:
        """Update CPU usage in background"""
        if self._is_cpu_check_running:
            return
            
        try:
            self._is_cpu_check_running = True
            # Get CPU usage over a short interval
            self._cpu_usage = psutil.cpu_percent(interval=0.1)
        except Exception as e:
            logger.error(f"Failed to get CPU usage: {e}")
            self._cpu_usage = 0
        finally:
            self._is_cpu_check_running = False

    async def _check_system_health(self) -> None:
        """Check system health and adjust service accordingly"""
        try:
            current_time = datetime.now()
            
            # Update performance metrics periodically
            if (current_time - self._last_performance_check).total_seconds() > 60:
                await self._update_cpu_usage()
                
                # Get memory usage
                memory = psutil.virtual_memory()
                self._memory_usage = memory.percent
                
                self._last_performance_check = current_time

            # Check if we should re-enable the service
            if not self._is_enabled and self._last_disable:
                if (current_time - self._last_disable).total_seconds() > self.DISABLE_COOLDOWN_MINUTES * 60:
                    # Check if system resources are back to normal
                    if (self._cpu_usage < self.CPU_THRESHOLD_PERCENT and 
                        self._memory_usage < self.MEMORY_THRESHOLD_PERCENT):
                        
                        self._is_enabled = True
                        self._last_disable = None
                        self._recent_errors.clear()
                        self._error_count = 0
                        
                        logger.info("Re-enabling Claude API - system resources normalized")
                        await self._notify_state_change(
                            "enabled",
                            "System resources normalized",
                            {
                                "CPU Usage": f"{self._cpu_usage:.1f}%",
                                "Memory Usage": f"{self._memory_usage:.1f}%"
                            }
                        )

            # Check if we should remove slowdown
            if self._is_slowed_down and self._last_slowdown:
                if (current_time - self._last_slowdown).total_seconds() > self.SLOWDOWN_COOLDOWN_MINUTES * 60:
                    self._is_slowed_down = False
                    self._last_slowdown = None
                    logger.info("Removing Claude API slowdown - cooldown period expired")

            # Check system load
            if (self._cpu_usage > self.CPU_THRESHOLD_PERCENT or 
                self._memory_usage > self.MEMORY_THRESHOLD_PERCENT):
                
                if self._is_enabled:
                    self._is_enabled = False
                    self._last_disable = current_time
                    
                    metrics = {
                        "CPU Usage": f"{self._cpu_usage:.1f}%",
                        "Memory Usage": f"{self._memory_usage:.1f}%"
                    }
                    
                    logger.warning(
                        f"Disabling Claude API - CPU: {self._cpu_usage}%, Memory: {self._memory_usage}%"
                    )
                    await self._notify_state_change(
                        "disabled",
                        "High system resource usage detected",
                        metrics
                    )

            # Clean up old error records
            error_cutoff = current_time - timedelta(minutes=self.ERROR_WINDOW_MINUTES)
            self._recent_errors = [
                error_time for error_time in self._recent_errors
                if error_time > error_cutoff
            ]
            self._error_count = len(self._recent_errors)

            # Check error rate
            if self._error_count >= self.MAX_ERRORS_BEFORE_DISABLE and self._is_enabled:
                self._is_enabled = False
                self._last_disable = current_time
                
                logger.warning(
                    f"Disabling Claude API - {self._error_count} errors in {self.ERROR_WINDOW_MINUTES} minutes"
                )
                await self._notify_state_change(
                    "disabled",
                    f"High error rate: {self._error_count} errors in {self.ERROR_WINDOW_MINUTES} minutes"
                )
                
            elif self._error_count >= self.MAX_ERRORS_BEFORE_SLOWDOWN and not self._is_slowed_down:
                self._is_slowed_down = True
                self._last_slowdown = current_time
                
                logger.warning(f"Enabling Claude API slowdown - {self._error_count} errors")
                await self._notify_state_change(
                    "slowed",
                    f"Moderate error rate: {self._error_count} errors in {self.ERROR_WINDOW_MINUTES} minutes"
                )

        except Exception as e:
            logger.error(f"Error during system health check: {e}")

    def _track_error(self) -> None:
        """Track API errors for degradation logic"""
        current_time = datetime.now()
        self._recent_errors.append(current_time)
        self._error_count = len(self._recent_errors)
        logger.warning(f"Claude API error tracked. Total recent errors: {self._error_count}")

    def _track_refusal(self) -> None:
        """Track Claude refusals for monitoring"""
        self._refusal_count += 1
        logger.info(f"Claude refusal tracked. Total refusals: {self._refusal_count}")
        
        # Schedule save to persist refusal count
        asyncio.create_task(self._schedule_save())

    def _track_stop_reason(self, stop_reason: str) -> None:
        """Track stop reasons for monitoring and analytics
        
        Args:
            stop_reason: The stop reason from Claude's response
        """
        # Normalize stop reason for tracking
        if stop_reason in self._stop_reason_counts:
            self._stop_reason_counts[stop_reason] += 1
        else:
            self._stop_reason_counts["unknown"] += 1
        
        logger.debug(f"Stop reason tracked: {stop_reason}. Counts: {self._stop_reason_counts}")
        
        # Schedule save to persist counts
        asyncio.create_task(self._schedule_save())

    async def _handle_stop_reason(self, response: Any, prompt: str, user_id: int, messages: List[Dict[str, Any]]) -> Optional[Tuple[str, Optional[str]]]:
        """Handle different stop reasons according to Anthropic's official guidance
        
        Args:
            response: API response object
            prompt: Original user prompt
            user_id: Discord user ID
            messages: Current conversation messages
            
        Returns:
            Optional[Tuple[str, Optional[str]]]: Response tuple if stop reason needs special handling, None otherwise
        """
        if not hasattr(response, 'stop_reason') or not response.stop_reason:
            return None
            
        stop_reason = response.stop_reason
        logger.info(f"Handling stop reason: {stop_reason}")
        
        # Track stop reason for analytics
        self._track_stop_reason(stop_reason)
        
        if stop_reason == "end_turn":
            # Normal completion - no special handling needed
            logger.debug("Response completed normally")
            return None
            
        elif stop_reason == "max_tokens":
            # Response was truncated due to token limit
            logger.warning(f"Response truncated due to max_tokens for user {user_id}")
            
            # Extract any available content
            response_text = ""
            for content_block in response.content:
                if content_block.type == "text":
                    response_text += content_block.text
            
            if response_text.strip():
                # Add truncation notice
                truncated_message = response_text.strip() + "\n\n*[응답이 길이 제한으로 잘렸어. 계속하려면 '계속해줘'라고 말해봐!]*"
                await self._track_request(prompt, truncated_message)
                return (truncated_message, None)
            else:
                # No content was generated before hitting limit
                error_message = "응답이 너무 길어져서 생성할 수 없었어. 더 간단한 질문으로 다시 물어봐줄래?"
                await self._track_request(prompt, error_message)
                return (error_message, None)
                
        elif stop_reason == "stop_sequence":
            # Claude encountered a custom stop sequence
            logger.info(f"Claude stopped at custom sequence: {getattr(response, 'stop_sequence', 'unknown')}")
            
            # Extract content before stop sequence
            response_text = ""
            for content_block in response.content:
                if content_block.type == "text":
                    response_text += content_block.text
            
            if response_text.strip():
                # Return content up to stop sequence
                await self._track_request(prompt, response_text)
                return (response_text.strip(), None)
            else:
                error_message = "응답 생성 중 중단되었어. 다시 시도해볼래?"
                await self._track_request(prompt, error_message)
                return (error_message, None)
                
        elif stop_reason == "tool_use":
            # Claude wants to use a tool - for web search, this should be handled automatically
            logger.info("Claude initiated tool use")
            
            # Extract any content before tool use
            response_text = ""
            for content_block in response.content:
                if content_block.type == "text":
                    response_text += content_block.text
            
            # For our Discord bot, tool use should be automatically handled by the API
            # If we get here, it means something went wrong with automatic tool execution
            if response_text.strip():
                tool_message = response_text.strip() + "\n\n*[도구 실행 중...]*"
                await self._track_request(prompt, tool_message)
                return (tool_message, None)
            else:
                error_message = "도구를 사용하려고 했지만 실행에 실패했어. 다시 시도해볼래?"
                await self._track_request(prompt, error_message)
                return (error_message, None)
                
        elif stop_reason == "pause_turn":
            # Claude paused a long-running operation (e.g., complex web search)
            logger.info("Claude paused for long-running operation")
            
            # For pause_turn, we should continue the conversation automatically
            try:
                # Add the paused response to conversation
                if response.content:
                    messages.append({"role": "assistant", "content": response.content})
                    
                # Build continuation request parameters
                continuation_params = {
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
                    "messages": messages,
                    "system": self.MUELSYSE_CONTEXT,
                    "tools": [{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 5
                    }]
                }
                
                # Add thinking or temperature
                if self.THINKING_ENABLED:
                    continuation_params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": self.THINKING_BUDGET_TOKENS
                    }
                else:
                    continuation_params["temperature"] = 0.5
                
                # Continue the conversation
                continuation_response = await self._client.messages.create(**continuation_params)
                
                # Recursively handle the continuation (in case it also pauses)
                continuation_result = await self._handle_stop_reason(continuation_response, prompt, user_id, messages)
                if continuation_result:
                    return continuation_result
                    
                # If continuation completed normally, return None to continue normal processing
                return None
                
            except Exception as e:
                logger.error(f"Failed to continue paused conversation: {e}")
                error_message = "복잡한 작업을 처리하는 중 문제가 발생했어. 다시 시도해볼래?"
                await self._track_request(prompt, error_message)
                return (error_message, None)
                
        elif stop_reason == "refusal":
            # Claude refused to respond due to safety concerns
            logger.warning(f"Claude refused to respond to user {user_id}")
            
            # Extract partial response if available
            partial_text = ""
            for content_block in response.content:
                if content_block.type == "text":
                    partial_text += content_block.text
            
            # Provide a helpful message to the user
            refusal_message = (
                "미안해, 그 요청에는 응답할 수 없어. "
                "다른 주제에 대해 이야기해볼래? 🤔"
            )
            
            # If there's partial content, include it
            if partial_text.strip():
                refusal_message = f"{partial_text.strip()}\n\n{refusal_message}"
            
            # Track the refusal for monitoring
            self._track_refusal()
            await self._track_request(prompt, refusal_message)
            
            return (refusal_message, None)
            
        else:
            # Unknown stop reason - log and handle gracefully
            logger.warning(f"Unknown stop reason: {stop_reason}")
            
            # Extract any available content
            response_text = ""
            for content_block in response.content:
                if content_block.type == "text":
                    response_text += content_block.text
            
            if response_text.strip():
                # Return available content with a note
                unknown_message = response_text.strip() + f"\n\n*[응답이 예상과 다르게 완료되었어 (stop_reason: {stop_reason})]*"
                await self._track_request(prompt, unknown_message)
                return (unknown_message, None)
            else:
                error_message = f"응답 생성 중 알 수 없는 문제가 발생했어 (stop_reason: {stop_reason}). 다시 시도해볼래?"
                await self._track_request(prompt, error_message)
                return (error_message, None)

    def _process_response(self, response: str, search_used: bool = False) -> str:
        """Process and format Claude's response before sending
        
        Args:
            response: Raw response from Claude
            search_used: Whether search grounding was used
            
        Returns:
            str: Processed response
        """
        if not response:
            return "미안해, 응답을 생성하지 못했어."
        
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
                        line = '📌 ' + line[2:]
                    
                    processed_lines.append(line)
        
        # Join all processed lines
        processed_response = '\n'.join(processed_lines)
        
        # Ensure response is not too long for Discord (2000 char limit)
        if len(processed_response) > 1900:
            processed_response = processed_response[:1897] + "..."
            
        return processed_response

    def _process_response_with_citations(self, response: str, citations: List[Any], search_used: bool = False) -> str:
        """Process Claude's response with inline citations and improved Korean formatting
        
        Args:
            response: Raw response from Claude
            citations: List of citation objects from Claude response
            search_used: Whether search grounding was used
            
        Returns:
            str: Processed response with inline clickable citations and proper Korean formatting
        """
        if not response:
            return "미안해, 응답을 생성하지 못했어."
        
        # Basic cleanup
        processed_response = response.strip()
        
        # Process citations first if they exist
        citation_map = {}
        if citations:
            for i, citation in enumerate(citations, 1):
                if hasattr(citation, 'url') and citation.url:
                    title = getattr(citation, 'title', f'Source {i}')
                    url = citation.url
                    
                    # Create clickable citation format
                    citation_key = f"[{i}]"
                    citation_link = f"[**[{i}]**]({url} \"{title}\")"
                    citation_map[citation_key] = citation_link
            
            # Replace citation markers with clickable links
            for citation_key, citation_link in citation_map.items():
                pattern = re.escape(citation_key)
                processed_response = re.sub(pattern, citation_link, processed_response)
        
        # Apply Korean-friendly text processing
        processed_response = self._format_korean_text(processed_response, search_used)
        
        # Add source section if citations exist
        if citation_map:
            processed_response += "\n\n**📚 참고 자료:**"
            for i, citation in enumerate(citations, 1):
                if hasattr(citation, 'url') and citation.url:
                    title = getattr(citation, 'title', f'Source {i}')
                    url = citation.url
                    domain = urlparse(url).netloc
                    processed_response += f"\n{i}. [{title}]({url}) - {domain}"
        
        # Ensure response is not too long for Discord
        if len(processed_response) > 1900:
            processed_response = processed_response[:1897] + "..."
            
        return processed_response

    def _format_korean_text(self, text: str, minimal_formatting: bool = False) -> str:
        """Format text with Korean-friendly line breaks and styling
        
        Args:
            text: Input text to format
            minimal_formatting: If True, apply minimal formatting (for search results)
            
        Returns:
            str: Formatted text with proper Korean handling
        """
        if not text:
            return text
            
        # Split into lines for processing
        lines = text.split('\n')
        processed_lines = []
        in_code_block = False
        
        for line in lines:
            line = line.rstrip()  # Remove trailing whitespace
            
            # Handle code blocks
            if '```' in line:
                in_code_block = not in_code_block
                if in_code_block and line.strip() == '```':
                    line = '```text'
                processed_lines.append(line)
                continue
                
            # Don't modify content inside code blocks
            if in_code_block:
                processed_lines.append(line)
                continue
                
            # Skip empty lines (will be handled later)
            if not line.strip():
                processed_lines.append('')
                continue
                
            # Apply formatting if not minimal
            if not minimal_formatting:
                line = self._apply_korean_styling(line)
            
            processed_lines.append(line)
        
        # Join lines with proper spacing for Korean text
        result = self._join_korean_lines(processed_lines)
        
        return result

    def _apply_korean_styling(self, line: str) -> str:
        """Apply Korean-friendly styling to a line of text
        
        Args:
            line: Single line of text
            
        Returns:
            str: Styled line with Korean-appropriate formatting
        """
        line = line.strip()
        if not line:
            return line
            
        # Korean punctuation patterns
        korean_endings = ['다', '요', '어', '아', '지', '네', '야', '죠', '까', '나']
        
        # Add emojis based on content and Korean context
        if line.endswith('?') or line.endswith('까?'):
            return '❓ ' + line
        elif any(line.endswith(ending + '.') or line.endswith(ending + '!') for ending in korean_endings):
            if '오류' in line or '에러' in line or '실패' in line:
                return '⚠️ ' + line
            elif '예시' in line or '예:' in line or '예를' in line:
                return '💡 ' + line
            elif '참고' in line or '주의' in line or '노트' in line:
                return '📝 ' + line
            elif '단계' in line or '방법' in line:
                return '✅ ' + line
        elif line.startswith(('- ', '* ', '• ')):
            return '📌 ' + line[2:]
        elif line.startswith(('1.', '2.', '3.', '4.', '5.')) and len(line) > 3:
            return '✨ ' + line
            
        return line

    def _join_korean_lines(self, lines: List[str]) -> str:
        """Join lines with Korean-appropriate spacing
        
        Args:
            lines: List of processed lines
            
        Returns:
            str: Joined text with proper Korean spacing
        """
        if not lines:
            return ''
            
        result_lines = []
        prev_line = ''
        
        for i, line in enumerate(lines):
            current_line = line.strip()
            
            # Always keep code blocks as-is
            if '```' in current_line:
                result_lines.append(line)
                prev_line = current_line
                continue
                
            # Handle empty lines
            if not current_line:
                # Add empty line only if previous line wasn't empty
                if prev_line.strip():
                    result_lines.append('')
                prev_line = current_line
                continue
                
            # Korean text flow rules
            if prev_line.strip():
                # Check if we need paragraph break
                needs_break = (
                    current_line.startswith(('📌', '✨', '💡', '⚠️', '📝', '✅', '❓')) or
                    prev_line.startswith(('📌', '✨', '💡', '⚠️', '📝', '✅', '❓')) or
                    current_line.startswith('**') or
                    prev_line.endswith(':') or
                    current_line.startswith('#')
                )
                
                if needs_break:
                    # Add empty line for paragraph break
                    if result_lines and result_lines[-1].strip():
                        result_lines.append('')
            
            result_lines.append(line)
            prev_line = current_line
        
        # Remove multiple consecutive empty lines
        final_lines = []
        empty_count = 0
        
        for line in result_lines:
            if not line.strip():
                empty_count += 1
                if empty_count <= 1:  # Allow max 1 empty line
                    final_lines.append(line)
            else:
                empty_count = 0
                final_lines.append(line)
        
        return '\n'.join(final_lines).strip()

    async def chat(self, prompt: str, user_id: int) -> Tuple[str, Optional[str]]:
        """Send a chat message to Claude with web search grounding
        
        Args:
            prompt: The user's message (text only)
            user_id: Discord user ID

        Returns:
            Tuple[str, Optional[str]]: (Claude's response, Source links if available)

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
                raise ValueError("Claude API not initialized")

            # Check user rate limits
            self._check_user_rate_limit(user_id)

            # Clean up expired sessions
            self._cleanup_expired_sessions()

            # Get or create chat session
            messages = await self._get_or_create_chat_session(user_id)

            # Add user message to session
            messages.append({"role": "user", "content": prompt})
            
            # Check token limits with full conversation context (thinking budget counts as input tokens)
            conversation_tokens = await self._count_conversation_tokens(messages, include_thinking=self.THINKING_ENABLED)
            self._check_token_thresholds(conversation_tokens)

            # Build API request parameters with system prompt
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
                "messages": messages,
                "system": self.MUELSYSE_CONTEXT,  # Official Anthropic system prompt for role assignment
                # Temporarily disable web search to test token usage
                # "tools": [{
                #     "type": "web_search_20250305",
                #     "name": "web_search",
                #     "max_uses": 5
                # }]
            }
            
            # Add thinking if enabled
            if self.THINKING_ENABLED:
                api_params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self.THINKING_BUDGET_TOKENS
                }
                logger.info(f"Thinking enabled with {self.THINKING_BUDGET_TOKENS} token budget")
                # Note: The thinking budget is reserved but only actual thinking usage counts toward output tokens
                # The budget allocation does get counted as part of input tokens in Anthropic's counting API
                # but actual thinking tokens are reported separately in the response usage
                # Note: temperature is incompatible with thinking, so we omit it
            else:
                # Only add temperature when thinking is disabled
                api_params["temperature"] = 0.5
            
            # Send message and get response with web search grounding and thinking
            response = await self._client.messages.create(**api_params)

            # Update last interaction time
            self._update_last_interaction(user_id)

            # Validate response
            if not response or not response.content:
                raise ValueError("Empty response from Claude")
                
            # Handle stop reasons according to Anthropic's official guidance
            stop_reason_result = await self._handle_stop_reason(response, prompt, user_id, messages)
            if stop_reason_result:
                return stop_reason_result
                
            # Process response and extract search results and thinking
            response_text = ""
            thinking_content = ""
            search_used = False
            thinking_used = False
            source_links = []
            citations = []
            
            for content_block in response.content:
                if content_block.type == "text":
                    response_text += content_block.text
                    
                    # Check for citations in text blocks (required by Anthropic)
                    if hasattr(content_block, 'citations') and content_block.citations:
                        citations.extend(content_block.citations)
                        search_used = True
                        logger.info(f"Found {len(content_block.citations)} citations in text block")
                        
                elif content_block.type == "thinking":
                    # Handle thinking content blocks
                    thinking_used = True
                    if hasattr(content_block, 'thinking'):
                        thinking_content = content_block.thinking
                        logger.info(f"Thinking content detected ({len(thinking_content)} chars)")
                        # Check for signature field (used for thinking encryption verification)
                        if hasattr(content_block, 'signature'):
                            logger.info("Thinking block has signature for verification")
                    else:
                        logger.info("Thinking block detected but no content available")
                        
                elif content_block.type == "redacted_thinking":
                    # Handle redacted thinking blocks (safety-flagged content)
                    thinking_used = True
                    logger.info("Redacted thinking block detected (encrypted for safety)")
                    # Note: redacted_thinking contains encrypted data, still counts as thinking usage
                        
                elif content_block.type == "web_search_tool_result":
                    # Handle web search tool results (official structure)
                    search_used = True
                    logger.info("Web search tool result detected")
                    
                    if hasattr(content_block, 'content') and content_block.content:
                        for result_item in content_block.content:
                            if hasattr(result_item, 'type') and result_item.type == "web_search_result":
                                title = getattr(result_item, 'title', 'Source')
                                url = getattr(result_item, 'url', '')
                                if url:
                                    domain = urlparse(url).netloc
                                    source_links.append((title, url, domain))
                                    logger.info(f"Added search result: {title} - {url} ({domain})")
                                    
                elif content_block.type == "server_tool_use":
                    # Handle server tool use (search query logging)
                    if hasattr(content_block, 'name') and content_block.name == "web_search":
                        search_used = True
                        logger.info("Web search detected via server_tool_use")
                        
                elif content_block.type == "tool_use":
                    # Legacy fallback for older tool_use format
                    if hasattr(content_block, 'name') and content_block.name == "web_search":
                        search_used = True
                        logger.info("Web search detected via tool_use (legacy)")

            # Process citations to extract additional sources
            for citation in citations:
                if hasattr(citation, 'type') and citation.type == "web_search_result_location":
                    title = getattr(citation, 'title', 'Source')
                    url = getattr(citation, 'url', '')
                    if url:
                        domain = urlparse(url).netloc
                        # Add to sources if not already present
                        if not any(existing_url == url for _, existing_url, _ in source_links):
                            source_links.append((title, url, domain))
                            logger.info(f"Added citation source: {title} - {url} ({domain})")

            if not response_text:
                raise ValueError("No text content in Claude response")

            # Add assistant response to session (clean version without web search artifacts)
            # Store only the core response text to avoid web search contamination in future conversations
            clean_response_text = response_text
            
            if thinking_used:
                # Store response with thinking blocks but clean text content
                assistant_content = []
                
                # Add all thinking and redacted_thinking blocks first
                for content_block in response.content:
                    if content_block.type == "thinking":
                        thinking_block = {"type": "thinking", "thinking": content_block.thinking}
                        if hasattr(content_block, 'signature'):
                            thinking_block["signature"] = content_block.signature
                        assistant_content.append(thinking_block)
                    elif content_block.type == "redacted_thinking":
                        # Preserve redacted thinking blocks as-is for API compatibility
                        redacted_block = {"type": "redacted_thinking"}
                        if hasattr(content_block, 'data'):
                            redacted_block["data"] = content_block.data
                        assistant_content.append(redacted_block)
                
                # Add clean text content (without web search citations that might contaminate future context)
                assistant_content.append({
                    "type": "text",
                    "text": clean_response_text
                })
                
                messages.append({"role": "assistant", "content": assistant_content})
                logger.info("Stored assistant response with thinking blocks (clean text)")
            else:
                # Regular text-only response (clean version)
                messages.append({"role": "assistant", "content": clean_response_text})
                logger.info("Stored clean assistant response without web search artifacts")
            
            # Trim conversation history if too long
            if len(messages) > self.MAX_HISTORY_LENGTH * 2:  # *2 because we have user+assistant pairs
                # Keep system message (if any) and recent conversation
                messages = messages[-self.MAX_HISTORY_LENGTH * 2:]

            # Update chat session
            self._chat_sessions[user_id] = messages

            # Process response with inline citations (with timing)
            processing_start = time.time()
            processed_response = self._process_response_with_citations(response_text, citations, search_used)
            processing_time = time.time() - processing_start
            logger.info(f"Text processing took: {processing_time:.3f}s")
            
            # Add note about redacted thinking if present
            thinking_start = time.time()
            has_redacted_thinking = any(
                content_block.type == "redacted_thinking" 
                for content_block in response.content
            )
            if has_redacted_thinking:
                processed_response += "\n\n*일부 추론 과정이 안전상의 이유로 암호화되었어.*"
            thinking_time = time.time() - thinking_start
            logger.info(f"Thinking check took: {thinking_time:.3f}s")

            # Track usage in background (non-blocking)
            tracking_start = time.time()
            asyncio.create_task(self._track_request_with_response_background(prompt, processed_response, response))
            tracking_time = time.time() - tracking_start
            logger.info(f"Usage tracking dispatch took: {tracking_time:.3f}s")
            
            # Track stop reason for normal completion (if not already tracked)
            if hasattr(response, 'stop_reason') and response.stop_reason:
                self._track_stop_reason(response.stop_reason)

            # Format source links if available (with timing)
            sources_start = time.time()
            formatted_sources = None
            if source_links:
                formatted_sources = self._format_sources(source_links)
            sources_time = time.time() - sources_start
            logger.info(f"Source formatting took: {sources_time:.3f}s")

            return (processed_response, formatted_sources)

        except anthropic.RateLimitError as e:
            self._track_error()
            logger.error(f"Claude rate limit exceeded: {e}")
            raise ValueError("API 요청 한도에 도달했어. 잠시 후에 다시 시도해줄래?") from e
        except anthropic.APIError as e:
            self._track_error()
            logger.error(f"Claude API error: {e}")
            raise ValueError(f"Claude API 요청에 실패했어: {str(e)}") from e
        except Exception as e:
            self._track_error()
            logger.error(f"Error in Claude chat: {e}")
            if "rate limit" in str(e).lower() or "quota" in str(e).lower():
                raise ValueError("Claude API가 현재 과부하 상태야. 잠시 후에 다시 시도해줄래?") from e
            else:
                raise ValueError(f"Claude API 요청에 실패했어: {str(e)}") from e

    def _format_sources(self, source_links: List[Tuple[str, str, str]]) -> str:
        """Format source links for display (matching Gemini format)
        
        Args:
            source_links: List of (title, url, domain) tuples
            
        Returns:
            str: Formatted source links
        """
        if not source_links:
            return "No sources available"
            
        # Remove duplicates while preserving order
        seen_urls = set()
        unique_sources = []
        for title, url, domain in source_links:
            if url not in seen_urls:
                seen_urls.add(url)
                unique_sources.append((title, url, domain))
        
        if not unique_sources:
            return "No sources available"
            
        # Format sources for Discord (matching Gemini style)
        formatted = "**Sources:**\n\n"
        for i, (title, url, domain) in enumerate(unique_sources[:5], 1):  # Limit to 5 sources
            # Truncate long titles but keep them readable
            display_title = title if len(title) <= 60 else title[:57] + "..."
            formatted += f"{i}. **[{display_title}]({url})**\n   {domain}\n\n"
        
        return formatted

    @property
    def usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics
        
        Returns:
            Dict[str, Any]: Usage statistics
        """
        current_time = datetime.now()
        
        # Calculate average tokens per request
        avg_prompt_tokens = (
            self._total_prompt_tokens // max(self._daily_requests, 1)
            if self._daily_requests > 0 else 0
        )
        avg_response_tokens = (
            self._total_response_tokens // max(self._daily_requests, 1)
            if self._daily_requests > 0 else 0
        )
        
        # Calculate recent usage (last hour)
        recent_requests = sum(
            1 for req in self._request_sizes
            if datetime.fromisoformat(req["timestamp"]) > current_time - timedelta(hours=1)
        )
        
        return {
            "service_name": "Claude API",
            "daily_requests": self._daily_requests,
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_response_tokens": self._total_response_tokens,
            "thinking_tokens_used": self._thinking_tokens_used,
            "hourly_token_count": self._hourly_token_count,
            "max_prompt_tokens": self._max_prompt_tokens,
            "max_response_tokens": self._max_response_tokens,
            "avg_prompt_tokens": avg_prompt_tokens,
            "avg_response_tokens": avg_response_tokens,
            "recent_requests_hour": recent_requests,
            "last_reset": self._last_reset.isoformat(),
            "is_enabled": self._is_enabled,
            "is_slowed_down": self._is_slowed_down,
            "error_count": self._error_count,
            "refusal_count": self._refusal_count,
            "stop_reason_counts": self._stop_reason_counts,
            "cpu_usage": self._cpu_usage,
            "memory_usage": self._memory_usage
        }

    def get_formatted_report(self) -> str:
        """Get formatted usage report
        
        Returns:
            str: Formatted report
        """
        stats = self.usage_stats
        current_time = datetime.now()
        
        # Calculate usage percentages
        daily_usage_pct = (stats["daily_requests"] / max(self.REQUESTS_PER_MINUTE * 24, 1)) * 100
        token_usage_pct = (stats["hourly_token_count"] / self.DAILY_TOKEN_LIMIT) * 100
        
        report = (
            f"📊 Claude API 사용 현황\n"
            f"🔄 오늘 요청: {stats['daily_requests']:,}회 ({daily_usage_pct:.1f}%)\n"
            f"🔤 사용 토큰: {stats['total_prompt_tokens'] + stats['total_response_tokens']:,} "
            f"({token_usage_pct:.1f}%)\n"
            f"📝 평균 프롬프트: {stats['avg_prompt_tokens']:,} 토큰\n"
            f"💬 평균 응답: {stats['avg_response_tokens']:,} 토큰\n"
        )
        
        # Add thinking tokens if any were used
        if stats.get('thinking_tokens_used', 0) > 0:
            report += f"🧠 생각 토큰: {stats['thinking_tokens_used']:,} 토큰\n"
            
        report += (
            f"⏱️ 최근 1시간: {stats['recent_requests_hour']:,}회\n"
            f"💻 시스템: CPU {stats['cpu_usage']:.1f}%, RAM {stats['memory_usage']:.1f}%\n"
        )
        
        if not stats["is_enabled"]:
            report += "⚠️ 서비스 일시 중단됨\n"
        elif stats["is_slowed_down"]:
            report += "🐌 속도 제한 모드\n"
        else:
            report += "✅ 정상 운영 중\n"
            
        if stats["error_count"] > 0:
            report += f"⚠️ 최근 오류: {stats['error_count']}회\n"
        
        if stats["refusal_count"] > 0:
            report += f"🚫 거부된 요청: {stats['refusal_count']}회\n"
            
        # Add stop reason summary for debugging (only if there are interesting patterns)
        stop_counts = stats.get("stop_reason_counts", {})
        total_responses = sum(stop_counts.values())
        if total_responses > 0:
            # Only show non-zero counts for unusual stop reasons
            unusual_stops = []
            if stop_counts.get("max_tokens", 0) > 0:
                unusual_stops.append(f"길이 제한: {stop_counts['max_tokens']}회")
            if stop_counts.get("pause_turn", 0) > 0:
                unusual_stops.append(f"일시 정지: {stop_counts['pause_turn']}회")
            if stop_counts.get("tool_use", 0) > 0:
                unusual_stops.append(f"도구 사용: {stop_counts['tool_use']}회")
            if stop_counts.get("unknown", 0) > 0:
                unusual_stops.append(f"알 수 없음: {stop_counts['unknown']}회")
                
            if unusual_stops:
                report += f"📊 응답 패턴: {', '.join(unusual_stops)}\n"
        
        return report

    @property
    def health_status(self) -> Dict[str, Any]:
        """Get service health status
        
        Returns:
            Dict[str, Any]: Health status information
        """
        return {
            "is_enabled": self._is_enabled,
            "is_slowed_down": self._is_slowed_down,
            "error_count": self._error_count,
            "cpu_usage": self._cpu_usage,
            "memory_usage": self._memory_usage,
            "last_slowdown": self._last_slowdown.isoformat() if self._last_slowdown else None,
            "last_disable": self._last_disable.isoformat() if self._last_disable else None,
            "active_sessions": len(self._chat_sessions),
            "recent_errors": len(self._recent_errors)
        }

    async def close(self) -> None:
        """Cleanup resources and flush pending data"""
        try:
            # Process any remaining usage data in the queue
            if hasattr(self, '_usage_queue') and self._usage_queue:
                async with self._batch_lock:
                    await self._process_usage_batch()
                    logger.info(f"Flushed {len(self._usage_queue)} pending usage records on shutdown")
            
            # Save final usage data
            await self._save_usage_data()
            
            self._client = None
            await super().close()
        except Exception as e:
            logger.error(f"Error during Claude API cleanup: {e}")

    async def validate_credentials(self) -> bool:
        """Validate Claude API credentials
        
        Returns:
            bool: True if credentials are valid
        """
        try:
            if not self.api_key:
                return False
                
            # Initialize the client with required headers
            client = anthropic.AsyncAnthropic(
                api_key=self.api_key,
                default_headers={
                    "anthropic-version": "2023-06-01"
                }
            )
            
            # Try a simple test request
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "test"}]
            )
            
            return bool(response.content)
            
        except Exception as e:
            logger.error(f"Failed to validate Claude credentials: {e}")
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

    async def _get_or_create_chat_session(self, user_id: int) -> List[Dict[str, Any]]:
        """Get existing chat session or create new one
        
        Args:
            user_id: Discord user ID
            
        Returns:
            List[Dict[str, str]]: Message history for the user
        """
        current_time = datetime.now()
        
        # Check if existing session has expired
        if user_id in self._chat_sessions and user_id in self._last_interaction:
            last_time = self._last_interaction[user_id]
            if (current_time - last_time).total_seconds() < self.CONTEXT_EXPIRY_MINUTES * 60:
                return self._chat_sessions[user_id]
        
        # Create new chat session (no need for character context in messages since we use system prompt)
        messages = []
        
        self._chat_sessions[user_id] = messages
        self._last_interaction[user_id] = current_time
        return messages

    def _update_last_interaction(self, user_id: int) -> None:
        """Update last interaction time for user
        
        Args:
            user_id: Discord user ID
        """
        self._last_interaction[user_id] = datetime.now()

    def _cleanup_expired_sessions(self) -> None:
        """Clean up expired chat sessions"""
        current_time = datetime.now()
        expired_users = []
        
        for user_id, last_time in self._last_interaction.items():
            if (current_time - last_time).total_seconds() > self.CONTEXT_EXPIRY_MINUTES * 60:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            if user_id in self._chat_sessions:
                del self._chat_sessions[user_id]
            del self._last_interaction[user_id]
        
        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired Claude chat sessions") 