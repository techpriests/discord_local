import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, date
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
    MAX_TOTAL_TOKENS = 20000  # Maximum total tokens (prompt + response) per interaction
    MAX_PROMPT_TOKENS = 18000  # Maximum tokens for user input
    TOKEN_WARNING_THRESHOLD = 0.8  # Warning at 80% of limit to provide safety margin
    RESPONSE_BUFFER_TOKENS = 4000  # Buffer for responses
    REQUESTS_PER_MINUTE = 50  # Standard API rate limit for Claude
    DAILY_TOKEN_LIMIT = 1_000_000  # Local limit: 5M tokens per day
    
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
    
    # Web search settings
    WEB_SEARCH_ENABLED = True  # Enable/disable web search
    WEB_SEARCH_MAX_USES = 1  # Limit searches per request (optimized for cost efficiency)
    WEB_SEARCH_COST_PER_1000 = 10  # $10 per 1000 searches
    
    # Web search token optimization settings
    WEB_SEARCH_RESULT_RETENTION_TURNS = 1  # Keep web search results for only 1 turn (current + previous)
    WEB_SEARCH_AGGRESSIVE_CLEANUP = True  # Enable aggressive cleanup of web search results
    WEB_SEARCH_CACHE_AGGRESSIVE = True  # Apply cache control more aggressively to web search results
    
    # Prompt caching settings
    PROMPT_CACHING_ENABLED = True  # Enable prompt caching for cost optimization
    CACHE_BREAKPOINTS_MAX = 4  # Maximum cache breakpoints allowed by Anthropic
    CACHE_MIN_TOKENS = 1024  # Minimum tokens required for caching (Claude Sonnet 4)
    CONVERSATION_CACHE_THRESHOLD = 3  # Cache conversation history after this many turns
    
    # Thinking settings
    THINKING_ENABLED = True  # Enable thinking for better reasoning quality
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

Web search guidelines (when web search tool is available):
- Answer as many questions as you can using your existing knowledge
- Only search the web for queries that you cannot confidently answer with your current knowledge
- Use web search for current events, recent developments, real-time information, or specific facts you're unsure about
- If someone asks about something that might have happened recently or involves current data, consider using web search
- Don't search for general knowledge, basic facts, or topics you're confident about

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
        
        # Add web search tracking
        self._web_search_requests = self._saved_usage.get("web_search_requests", 0)
        self._web_search_cost = self._saved_usage.get("web_search_cost", 0.0)
        
        # Add prompt caching tracking
        self._cache_creation_tokens = self._saved_usage.get("cache_creation_tokens", 0)
        self._cache_read_tokens = self._saved_usage.get("cache_read_tokens", 0)
        self._cache_hits = self._saved_usage.get("cache_hits", 0)
        self._cache_misses = self._saved_usage.get("cache_misses", 0)
        

        
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
        
        # Initialize web search optimization settings with defaults
        self.WEB_SEARCH_RESULT_RETENTION_TURNS = getattr(self, 'WEB_SEARCH_RESULT_RETENTION_TURNS', 1)
        self.WEB_SEARCH_AGGRESSIVE_CLEANUP = getattr(self, 'WEB_SEARCH_AGGRESSIVE_CLEANUP', True)
        self.WEB_SEARCH_CACHE_AGGRESSIVE = getattr(self, 'WEB_SEARCH_CACHE_AGGRESSIVE', True)

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
                    "web_search_requests": self._web_search_requests,
                    "web_search_cost": self._web_search_cost,
                    "cache_creation_tokens": self._cache_creation_tokens,
                    "cache_read_tokens": self._cache_read_tokens,
                    "cache_hits": self._cache_hits,
                    "cache_misses": self._cache_misses,
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
    
    def configure_web_search(self, enabled: bool = True, max_uses: int = 1) -> None:
        """Configure web search settings following official documentation
        
        Args:
            enabled: Whether to enable web search (Claude decides when to use it)
            max_uses: Maximum web searches per request (1-5, default 1 for cost efficiency)
        """
        self.WEB_SEARCH_ENABLED = enabled
        self.WEB_SEARCH_MAX_USES = max(1, min(5, max_uses))  # Clamp between 1-5
        logger.info(f"Web search configured: enabled={enabled}, max_uses={self.WEB_SEARCH_MAX_USES}")
    
    def configure_web_search_optimization(self, 
                                        retention_turns: int = 1, 
                                        aggressive_cleanup: bool = True,
                                        aggressive_caching: bool = True) -> None:
        """Configure web search token optimization settings
        
        Args:
            retention_turns: Number of conversation turns to keep web search results (1-3, default 1)
            aggressive_cleanup: Whether to aggressively remove old web search results
            aggressive_caching: Whether to apply cache control more aggressively to web search results
        """
        self.WEB_SEARCH_RESULT_RETENTION_TURNS = max(1, min(3, retention_turns))
        self.WEB_SEARCH_AGGRESSIVE_CLEANUP = aggressive_cleanup
        self.WEB_SEARCH_CACHE_AGGRESSIVE = aggressive_caching
        logger.info(f"Web search optimization configured: retention={self.WEB_SEARCH_RESULT_RETENTION_TURNS}, "
                   f"aggressive_cleanup={aggressive_cleanup}, aggressive_caching={aggressive_caching}")
    
    def get_web_search_config(self) -> Dict[str, Any]:
        """Get current web search configuration
        
        Returns:
            Dict[str, Any]: Current web search settings
        """
        return {
            "enabled": self.WEB_SEARCH_ENABLED,
            "max_uses": self.WEB_SEARCH_MAX_USES,
            "requests_used": self._web_search_requests,
            "total_cost": self._web_search_cost,
            "optimization": {
                "retention_turns": getattr(self, 'WEB_SEARCH_RESULT_RETENTION_TURNS', 1),
                "aggressive_cleanup": getattr(self, 'WEB_SEARCH_AGGRESSIVE_CLEANUP', True),
                "aggressive_caching": getattr(self, 'WEB_SEARCH_CACHE_AGGRESSIVE', True)
            }
        }
    
    def configure_prompt_caching(self, enabled: bool = True) -> None:
        """Configure prompt caching settings
        
        Args:
            enabled: Whether to enable prompt caching for cost optimization
        """
        self.PROMPT_CACHING_ENABLED = enabled
        logger.info(f"Prompt caching configured: enabled={enabled}")
    
    def get_prompt_caching_config(self) -> Dict[str, Any]:
        """Get current prompt caching configuration and performance
        
        Returns:
            Dict[str, Any]: Current prompt caching settings and stats
        """
        cache_hits = self._cache_hits
        cache_misses = self._cache_misses
        total_requests = cache_hits + cache_misses
        hit_rate = (cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        # Calculate cost savings (90% reduction on cache hits vs normal pricing)
        cache_savings_tokens = self._cache_read_tokens * 0.9
        estimated_savings = (cache_savings_tokens / 1_000_000) * 3.0  # $3/MTok for Claude Sonnet 4
        
        return {
            "enabled": self.PROMPT_CACHING_ENABLED,
            "min_tokens_required": self.CACHE_MIN_TOKENS,
            "max_breakpoints": self.CACHE_BREAKPOINTS_MAX,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "hit_rate_percent": hit_rate,
            "tokens_written": self._cache_creation_tokens,
            "tokens_read": self._cache_read_tokens,
            "estimated_cost_savings": estimated_savings
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
                        "max_uses": 1
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
            messages: List of message dictionaries with EXACT preservation format from Claude API
                     content can be: str, list of dicts, or raw Anthropic content blocks (compliance mode)
            include_thinking: Whether to include thinking budget in token calculation
                             Note: This adds the thinking BUDGET to input tokens, not actual thinking usage
            
        Returns:
            int: Number of tokens for the full conversation
        """
        try:
            if not self._client:
                # Fallback: estimate based on message content
                return self._estimate_conversation_tokens_fallback(messages)
                
            # Build request parameters  
            current_date = date.today().strftime("%B %d %Y")
            system_prompt_with_date = f"{self.MUELSYSE_CONTEXT}\n\nToday's date is {current_date}."
            
            # Convert messages to compatible format for token counting while preserving structure
            compatible_messages = self._prepare_messages_for_token_counting(messages)
            
            count_params = {
                "model": "claude-sonnet-4-20250514",
                "messages": compatible_messages,
                # Include system prompt in the same format as actual requests (list format for consistency)
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt_with_date,
                        "cache_control": {"type": "ephemeral"}
                    }
                ] if self.PROMPT_CACHING_ENABLED else system_prompt_with_date,
                # Include web search tools for accurate token counting
                "tools": [{
                    "type": "web_search_20250305", 
                    "name": "web_search",
                    "max_uses": self.WEB_SEARCH_MAX_USES
                }]
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
                return self._estimate_conversation_tokens_fallback(messages)
                
        except Exception as e:
            error_msg = str(e)
            if "encrypted_content" in error_msg:
                logger.warning(f"Token counting failed due to encrypted web search content: {e}")
                logger.info("This is expected - token counting API doesn't support encrypted_content from web search results")
                logger.info("Note: Encrypted web search content DOES count toward actual input tokens despite counting API limitations")
            else:
                logger.warning(f"Failed to count conversation tokens: {e}")
            
            # Fallback: estimate based on message content
            return self._estimate_conversation_tokens_fallback(messages)

    def _prepare_messages_for_token_counting(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare messages for token counting API, handling cookbook approach formats
        
        Args:
            messages: Messages in various formats (string, content blocks, exact preservation)
            
        Returns:
            List[Dict[str, Any]]: Messages compatible with token counting API
        """
        compatible_messages = []
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if isinstance(content, str):
                # Simple string content - use as-is (early conversation turns)
                compatible_messages.append({"role": role, "content": content})
                
            elif isinstance(content, list):
                # Content blocks format - handle both dict and Anthropic objects
                processed_blocks = []
                for block in content:
                    if hasattr(block, 'type'):  # Anthropic content block object
                        processed_block = {"type": block.type}
                        
                        if block.type == "text":
                            processed_block["text"] = getattr(block, 'text', '')
                        elif block.type == "thinking":
                            processed_block["thinking"] = getattr(block, 'thinking', '')
                            # Include signature if present for accurate token counting
                            if hasattr(block, 'signature'):
                                processed_block["signature"] = block.signature
                        elif block.type == "redacted_thinking":
                            processed_block["data"] = getattr(block, 'data', '')
                        elif block.type == "server_tool_use":
                            processed_block["id"] = getattr(block, 'id', '')
                            processed_block["name"] = getattr(block, 'name', '')
                            processed_block["input"] = getattr(block, 'input', {})
                        elif block.type == "web_search_tool_result":
                            processed_block["tool_use_id"] = getattr(block, 'tool_use_id', '')
                            # Filter out encrypted content for token counting API compatibility
                            original_content = getattr(block, 'content', [])
                            filtered_content = []
                            for item in original_content:
                                if hasattr(item, 'type') and item.type == "web_search_result":
                                    # Create sanitized version without encrypted_content for token counting
                                    sanitized_item = {
                                        "type": "web_search_result",
                                        "url": getattr(item, 'url', ''),
                                        "title": getattr(item, 'title', ''),
                                        "page_age": getattr(item, 'page_age', '')
                                        # Note: encrypted_content is excluded for token counting API compatibility
                                    }
                                    filtered_content.append(sanitized_item)
                                elif isinstance(item, dict):
                                    # Handle dict format, exclude encrypted_content
                                    sanitized_item = {k: v for k, v in item.items() if k != "encrypted_content"}
                                    filtered_content.append(sanitized_item)
                                else:
                                    # Keep other content types as-is
                                    filtered_content.append(item)
                            processed_block["content"] = filtered_content
                        # Note: Cache control is ignored for token counting as it doesn't affect token count
                        
                        processed_blocks.append(processed_block)
                        
                    elif isinstance(block, dict):  # Already dict format (cookbook user messages)
                        # Clean copy without problematic fields for token counting
                        clean_block = {k: v for k, v in block.items() if k not in ["cache_control"]}
                        
                        # Special handling for web_search_tool_result blocks with encrypted content
                        if block.get("type") == "web_search_tool_result" and "content" in clean_block:
                            filtered_content = []
                            for item in clean_block["content"]:
                                if isinstance(item, dict):
                                    # Remove encrypted_content for token counting API compatibility
                                    sanitized_item = {k: v for k, v in item.items() if k != "encrypted_content"}
                                    filtered_content.append(sanitized_item)
                                else:
                                    filtered_content.append(item)
                            clean_block["content"] = filtered_content
                        
                        processed_blocks.append(clean_block)
                        
                compatible_messages.append({"role": role, "content": processed_blocks})
                
            else:
                # Fallback for unknown format
                logger.warning(f"Unknown content format in message: {type(content)}")
                compatible_messages.append({"role": role, "content": str(content)})
                
        return compatible_messages

    def _estimate_conversation_tokens_fallback(self, messages: List[Dict[str, Any]]) -> int:
        """Fallback token estimation when API counting fails
        
        Args:
            messages: Messages in any format
            
        Returns:
            int: Estimated token count
        """
        total_chars = 0
        
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Handle content blocks
                for block in content:
                    if hasattr(block, 'type'):  # Anthropic content block object
                        if block.type == "text":
                            total_chars += len(getattr(block, 'text', ''))
                        elif block.type == "thinking":
                            total_chars += len(getattr(block, 'thinking', ''))
                        elif block.type == "redacted_thinking":
                            # Estimate tokens for redacted thinking (encrypted data)
                            total_chars += len(getattr(block, 'data', '')) // 2
                        elif block.type == "web_search_tool_result":
                            # Estimate tokens for web search results (approximate)
                            content = getattr(block, 'content', [])
                            for item in content:
                                if hasattr(item, 'title'):
                                    total_chars += len(getattr(item, 'title', ''))
                                if hasattr(item, 'url'):
                                    total_chars += len(getattr(item, 'url', '')) // 2  # URLs are less token-dense
                                # encrypted_content is harder to estimate, use rough approximation
                                if hasattr(item, 'encrypted_content'):
                                    total_chars += 500  # Rough estimate for search result content
                    elif isinstance(block, dict):  # Dict format
                        if block.get("type") == "text":
                            total_chars += len(block.get("text", ""))
                        elif block.get("type") == "thinking":
                            total_chars += len(block.get("thinking", ""))
                        elif block.get("type") == "redacted_thinking":
                            total_chars += len(block.get("data", "")) // 2
                        elif block.get("type") == "web_search_tool_result":
                            # Estimate tokens for web search results (dict format)
                            content = block.get("content", [])
                            for item in content:
                                if isinstance(item, dict):
                                    total_chars += len(item.get("title", ""))
                                    total_chars += len(item.get("url", "")) // 2
                                    if "encrypted_content" in item:
                                        total_chars += 500  # Rough estimate
        
        return total_chars // 4  # Rough estimation: 4 characters per token

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
            
            logger.info(f"Processed {queue_size} usage records in batch")
            
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
            logger.info("Claude paused for long-running operation - COMPLIANCE: preserving exact response")
            
            # For pause_turn, we should continue the conversation automatically
            try:
                # 🔧 COMPLIANCE: Store the paused response EXACTLY as received from Claude
                # This preserves thinking block signatures and tool result structures
                if response.content:
                    paused_message = {
                        "role": "assistant", 
                        "content": response.content  # Preserve EXACT content blocks
                    }
                    messages.append(paused_message)
                    logger.info(f"✅ COMPLIANCE: Stored paused response exactly as received with {len(response.content)} content blocks")
                    
                # Build continuation request parameters with current date
                from datetime import date
                current_date = date.today().strftime("%B %d %Y")
                system_prompt_with_date = f"{self.MUELSYSE_CONTEXT}\n\nToday's date is {current_date}."
                
                continuation_params = {
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
                    "messages": messages,
                    "system": system_prompt_with_date,  # Use consistent system prompt format
                    "tools": [{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": self.WEB_SEARCH_MAX_USES
                    }],
                    "tool_choice": {"type": "auto"}  # Consistent with main chat method
                }
                
                # Add thinking if enabled
                if self.THINKING_ENABLED:
                    continuation_params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": self.THINKING_BUDGET_TOKENS
                    }
                    logger.info(f"Thinking enabled for continuation with {self.THINKING_BUDGET_TOKENS} token budget")
                    # Note: Temperature, top_k, and other sampling parameters are incompatible with thinking
                
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

    async def chat(self, prompt: str, user_id: int, tool_choice: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[str]]:
        """Send a chat message to Claude with web search grounding
        
        Args:
            prompt: The user's message (text only)
            user_id: Discord user ID
            tool_choice: Optional tool choice parameter following official documentation
                        - {"type": "auto"}: Claude decides (default)
                        - {"type": "any"}: Must use one of the tools
                        - {"type": "tool", "name": "web_search"}: Force web search

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

            # Optimize conversation history by removing stale web search results
            messages = self._optimize_conversation_history(messages)

            # 📚 COOKBOOK: Cache Breakpoint 3 - User Messages (Incremental Conversation Caching)
            # Cache last user message as conversation grows (official pattern)
            conversation_turns = len(messages) // 2  # Rough estimate: user+assistant pairs
            
            if (self.PROMPT_CACHING_ENABLED and conversation_turns >= self.CONVERSATION_CACHE_THRESHOLD):
                # Apply cache control to user message for incremental conversation caching
                user_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ]
                }
                messages.append(user_message)
                logger.info(f"📚 COOKBOOK: Applied user message caching at turn {conversation_turns + 1}")
            else:
                # Simple user message for early conversation turns
                messages.append({"role": "user", "content": prompt})
                logger.info(f"Added simple user message (turn {conversation_turns + 1})")
            
            # Check token limits with full conversation context (thinking budget counts as input tokens)
            conversation_tokens = await self._count_conversation_tokens(messages, include_thinking=self.THINKING_ENABLED)
            self._check_token_thresholds(conversation_tokens)

            # Build API request parameters with prompt caching
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": self.MAX_TOTAL_TOKENS - self.MAX_PROMPT_TOKENS,
                "messages": messages,
            }
            
            # 📚 COOKBOOK: Cache Breakpoint 1 - Tools
            # Add web search tool with prompt caching following official patterns
            if self.WEB_SEARCH_ENABLED:
                web_search_tool = {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self.WEB_SEARCH_MAX_USES,  # Optimized for cost efficiency
                }
                
                # Add cache control to tools if prompt caching is enabled
                if self.PROMPT_CACHING_ENABLED:
                    web_search_tool["cache_control"] = {"type": "ephemeral"}
                
                api_params["tools"] = [web_search_tool]
                
                # Add tool choice (following official cookbook patterns)
                if tool_choice:
                    api_params["tool_choice"] = tool_choice
                    logger.info(f"Tool choice specified: {tool_choice}")
                else:
                    # Explicitly set to "auto" as per cookbook best practices
                    api_params["tool_choice"] = {"type": "auto"}
                    logger.info(f"Tool choice set to auto - Claude will decide when to use web search")
                
                logger.info(f"Web search tool configured: max_uses={self.WEB_SEARCH_MAX_USES}, caching={self.PROMPT_CACHING_ENABLED}")
            
            # 📚 COOKBOOK: Cache Breakpoint 2 - System Instructions
            # Include current date as per cookbook best practices
            current_date = date.today().strftime("%B %d %Y")
            system_prompt_with_date = f"{self.MUELSYSE_CONTEXT}\n\nToday's date is {current_date}."
            
            if self.PROMPT_CACHING_ENABLED:
                api_params["system"] = [
                    {
                        "type": "text",
                        "text": system_prompt_with_date,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
                logger.info(f"System prompt configured with cache control and current date: {current_date}")
            else:
                api_params["system"] = system_prompt_with_date
                logger.info(f"System prompt configured with current date: {current_date}")
            
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
                # Note: temperature, top_k, and forced tool use are incompatible with thinking
            # Temperature, top_k, and other sampling parameters are incompatible with thinking
            # Since thinking is enabled, we omit all incompatible parameters
            
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
            tool_use_blocks = []  # Store tool_use blocks for conversation history
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
                
                elif content_block.type == "tool_use":
                    # Handle tool_use blocks (critical for thinking + tool workflows)
                    if hasattr(content_block, 'name') and content_block.name == "web_search":
                        search_used = True
                        logger.info(f"Tool use detected: {content_block.name}")
                        
                        # Store complete tool_use block for conversation history (required by Anthropic)
                        tool_block = {
                            "type": "tool_use",
                            "id": getattr(content_block, 'id', ''),
                            "name": content_block.name,
                            "input": getattr(content_block, 'input', {})
                        }
                        tool_use_blocks.append(tool_block)
                        logger.info(f"Preserved tool_use block: {content_block.name} (id: {tool_block['id']})")
                    else:
                        # Handle other potential tool types
                        logger.info(f"Unknown tool use detected: {getattr(content_block, 'name', 'unknown')}")
                        
                elif content_block.type == "web_search_tool_result":
                    # Handle web search tool results (official structure)
                    search_used = True
                    logger.info("Web search tool result detected")
                    
                    # Check for errors in web search results (per official docs)
                    if hasattr(content_block, 'content'):
                        if isinstance(content_block.content, dict) and content_block.content.get('type') == 'web_search_tool_result_error':
                            error_code = content_block.content.get('error_code', 'unknown')
                            error_messages = {
                                'too_many_requests': '웹 검색 요청 한도 초과',
                                'invalid_input': '잘못된 검색 쿼리',
                                'max_uses_exceeded': f'검색 횟수 한도 초과 (최대 {self.WEB_SEARCH_MAX_USES}회)',
                                'query_too_long': '검색 쿼리가 너무 길어',
                                'unavailable': '웹 검색 서비스 일시 불가'
                            }
                            user_message = error_messages.get(error_code, f'웹 검색 오류: {error_code}')
                            logger.warning(f"Web search error: {error_code} - {user_message}")
                            # Don't count failed searches toward usage (per docs)
                            search_used = False
                    
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
                        
                else:
                    # Log any unhandled content block types for debugging
                    logger.warning(f"Unhandled content block type: {content_block.type}")

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

            # Handle special case: tool_use without text response (Claude wants to use tools)
            if tool_use_blocks and not response_text:
                # This is a tool-only response - Claude is requesting to use tools
                logger.info(f"Tool-only response detected with {len(tool_use_blocks)} tool requests")
                # Set a default response indicating tool use is happening
                response_text = "도구를 사용해서 정보를 찾고 있어..."
                
            if not response_text and not tool_use_blocks:
                raise ValueError("No text content or tool use in Claude response")

            # 🔧 CRITICAL: MAXIMUM COMPLIANCE with official Extended Thinking + Tools cookbook
            # Preserve EXACT thinking blocks with cryptographic signatures to prevent validation failures
            # Store complete assistant response exactly as received for multi-turn conversations
            
            if thinking_used or tool_use_blocks or search_used:
                # COOKBOOK COMPLIANCE: Store response exactly as received from Claude API
                # This preserves thinking block signatures and ensures proper tool conversation flow
                # DO NOT reconstruct content blocks - use the exact response.content
                assistant_message = {
                    "role": "assistant", 
                    "content": response.content  # Preserve EXACT content blocks from Claude
                }
                
                messages.append(assistant_message)
                logger.info(f"✅ COMPLIANCE: Stored assistant response exactly as received from Claude with {len(response.content)} content blocks")
                
                # Log compliance details for debugging
                content_types = [getattr(block, 'type', 'unknown') for block in response.content]
                logger.info(f"Preserved content block types: {content_types}")
                
                # Check for thinking signatures to verify compliance
                thinking_blocks_with_signatures = sum(
                    1 for block in response.content 
                    if (hasattr(block, 'type') and block.type == "thinking" and 
                        hasattr(block, 'signature'))
                )
                if thinking_blocks_with_signatures > 0:
                    logger.info(f"✅ Preserved {thinking_blocks_with_signatures} thinking blocks with cryptographic signatures")
                
                # 📚 COOKBOOK: Cache Breakpoint 4 - Web Search Results (Optimized Strategy)
                # Apply strategic cache control for maximum token efficiency
                if self.PROMPT_CACHING_ENABLED and search_used:
                    aggressive_caching = getattr(self, 'WEB_SEARCH_CACHE_AGGRESSIVE', True)
                    
                    if aggressive_caching:
                        # Apply cache control to ALL web search tool results for maximum efficiency
                        cache_applied_count = 0
                        for content_block in response.content:
                            if hasattr(content_block, 'type') and content_block.type == "web_search_tool_result":
                                # Apply cache control to all search results for better token efficiency
                                if not hasattr(content_block, 'cache_control'):
                                    content_block.cache_control = {"type": "ephemeral"}
                                    cache_applied_count += 1
                        
                        if cache_applied_count > 0:
                            logger.info(f"📚 Applied aggressive cache control to {cache_applied_count} web search results "
                                       f"for maximum token efficiency")
                    else:
                        # Conservative approach: cache only the last web search result
                        for i in range(len(response.content) - 1, -1, -1):
                            content_block = response.content[i]
                            if hasattr(content_block, 'type') and content_block.type == "web_search_tool_result":
                                if not hasattr(content_block, 'cache_control'):
                                    content_block.cache_control = {"type": "ephemeral"}
                                    logger.info("📚 Applied cache control to last web search result")
                                break
                
            else:
                # Text-only response - store as simple string for efficiency
                # This path is used when no thinking or tools are involved
                messages.append({"role": "assistant", "content": response_text})
                logger.info("Stored text-only assistant response as simple string")
            
            # Trim conversation history if too long, preserving web search efficiency
            if len(messages) > self.MAX_HISTORY_LENGTH * 2:  # *2 because we have user+assistant pairs
                # Keep recent conversation but be smart about web search results
                # Recent messages are more likely to have cached web search results
                messages = messages[-self.MAX_HISTORY_LENGTH * 2:]
                logger.info(f"Trimmed conversation to {len(messages)} messages, preserving recent web search cache")

            # Update chat session
            self._chat_sessions[user_id] = messages

            # Process response with inline citations (with timing)
            processing_start = time.perf_counter()
            processed_response = self._process_response_with_citations(response_text, citations, search_used)
            processing_time = time.perf_counter() - processing_start
            logger.info(f"Text processing took: {processing_time:.6f}s")
            
            # Add note about redacted thinking if present
            thinking_start = time.perf_counter()
            has_redacted_thinking = any(
                content_block.type == "redacted_thinking" 
                for content_block in response.content
            )
            if has_redacted_thinking:
                processed_response += "\n\n*일부 추론 과정이 안전상의 이유로 암호화되었어.*"
            thinking_time = time.perf_counter() - thinking_start
            logger.info(f"Thinking check took: {thinking_time:.6f}s")

            # Track web search and cache usage if used
            if hasattr(response, 'usage'):
                usage = response.usage
                
                # Track web search usage
                if search_used and hasattr(usage, 'server_tool_use'):
                    # Use getattr instead of .get() since server_tool_use is a Pydantic model, not a dict
                    server_tool_usage = usage.server_tool_use
                    web_search_count = getattr(server_tool_usage, 'web_search_requests', 0)
                    if web_search_count > 0:
                        self._web_search_requests += web_search_count
                        search_cost = (web_search_count / 1000.0) * self.WEB_SEARCH_COST_PER_1000
                        self._web_search_cost += search_cost
                        logger.info(f"Web search: {web_search_count} requests, cost: ${search_cost:.4f}")
                    else:
                        # If no direct web_search_requests field, check if server tool use occurred
                        logger.info("Web search tool used but no request count available")
                
                # Track prompt caching performance 
                if self.PROMPT_CACHING_ENABLED:
                    cache_creation = getattr(usage, 'cache_creation_input_tokens', 0)
                    cache_read = getattr(usage, 'cache_read_input_tokens', 0)
                    
                    if cache_creation > 0:
                        self._cache_creation_tokens += cache_creation
                        self._cache_misses += 1
                        logger.info(f"Cache miss: {cache_creation:,} tokens written to cache")
                    
                    if cache_read > 0:
                        self._cache_read_tokens += cache_read
                        self._cache_hits += 1
                        cache_savings_pct = ((cache_read * 3.0 - cache_read * 0.3) / (cache_read * 3.0)) * 100 if cache_read > 0 else 0
                        logger.info(f"Cache hit: {cache_read:,} tokens read from cache ({cache_savings_pct:.1f}% cost savings)")
                    
                    if cache_creation == 0 and cache_read == 0:
                        logger.info(f"No cache activity - input tokens: {prompt_tokens:,}, threshold: 1024")

            # Track usage in background (non-blocking) - only time the dispatch
            tracking_start = time.perf_counter()
            
            # Log immediate token usage (before background processing)
            if hasattr(response, 'usage'):
                usage = response.usage
                prompt_tokens = getattr(usage, 'input_tokens', 0)
                response_tokens = getattr(usage, 'output_tokens', 0)
                thinking_tokens = getattr(usage, 'thinking_tokens', 0)
                total_tokens = prompt_tokens + response_tokens
                
                logger.info(f"Token usage - Prompt: {prompt_tokens:,}, Response: {response_tokens:,}, "
                          f"Thinking: {thinking_tokens:,}, Total: {total_tokens:,}")
                
                # Log Korean usage summary
                logger.info(f"사용량 - 입력: {prompt_tokens:,}토큰, 출력: {response_tokens:,}토큰, "
                          f"사고: {thinking_tokens:,}토큰, 전체: {total_tokens:,}토큰")
            
            asyncio.create_task(self._track_request_with_response_background(prompt, processed_response, response))
            tracking_time = time.perf_counter() - tracking_start
            logger.info(f"Usage tracking dispatch took: {tracking_time:.6f}s")
            
            # Track stop reason for normal completion (if not already tracked)
            if hasattr(response, 'stop_reason') and response.stop_reason:
                self._track_stop_reason(response.stop_reason)

            # Format source links if available (with timing)
            sources_start = time.perf_counter()
            formatted_sources = None
            if source_links:
                formatted_sources = self._format_sources(source_links)
            sources_time = time.perf_counter() - sources_start
            logger.info(f"Source formatting took: {sources_time:.6f}s")

            return (processed_response, formatted_sources)

        except anthropic.RateLimitError as e:
            self._track_error()
            logger.error(f"Claude rate limit exceeded: {e}")
            raise ValueError("API 요청 한도에 도달했어. 잠시 후에 다시 시도해줄래?") from e
        except anthropic.APIError as e:
            self._track_error()
            error_message = str(e)
            logger.error(f"Claude API error: {error_message}")
            
            # Handle specific compliance-related errors
            if "signature" in error_message.lower() or "validation" in error_message.lower():
                logger.error("🚨 COMPLIANCE ERROR: Thinking block signature validation failed")
                # Clear potentially corrupted session to prevent further signature errors
                if user_id in self._chat_sessions:
                    del self._chat_sessions[user_id]
                    logger.info(f"Cleared chat session for user {user_id} due to signature validation failure")
                raise ValueError("대화 상태에 문제가 발생했어. 새로운 대화를 시작해줄래?") from e
            elif "content block" in error_message.lower() or "format" in error_message.lower():
                logger.error("🚨 COMPLIANCE ERROR: Content block format validation failed")
                # Clear session and suggest retry
                if user_id in self._chat_sessions:
                    del self._chat_sessions[user_id]
                    logger.info(f"Cleared chat session for user {user_id} due to content format error")
                raise ValueError("메시지 형식에 문제가 발생했어. 새로운 대화를 시작해줄래?") from e
            elif "thinking" in error_message.lower():
                logger.error("🚨 COMPLIANCE ERROR: Thinking-related API error")
                raise ValueError("추론 처리 중 문제가 발생했어. 다시 시도해볼래?") from e
            else:
                raise ValueError(f"Claude API 요청에 실패했어: {error_message}") from e
                
        except Exception as e:
            self._track_error()
            error_message = str(e)
            logger.error(f"Error in Claude chat: {error_message}")
            
            # Handle specific error types that might indicate compliance issues
            if "signature" in error_message.lower():
                logger.error("🚨 CRITICAL: Signature-related error in chat processing")
                # Clear the problematic session
                if user_id in self._chat_sessions:
                    del self._chat_sessions[user_id]
                    logger.info(f"Cleared chat session for user {user_id} due to signature error")
                raise ValueError("대화 보안에 문제가 발생했어. 새로운 대화를 시작해줄래?") from e
            elif "content block" in error_message.lower():
                logger.error("🚨 CRITICAL: Content block handling error")
                raise ValueError("메시지 처리 중 구조적 문제가 발생했어. 다시 시도해볼래?") from e
            elif "rate limit" in error_message.lower() or "quota" in error_message.lower():
                raise ValueError("Claude API가 현재 과부하 상태야. 잠시 후에 다시 시도해줄래?") from e
            else:
                raise ValueError(f"Claude API 요청에 실패했어: {error_message}") from e

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
        
        # Get compliance status for enhanced reporting
        compliance_status = self.get_compliance_status()
        
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
            "web_search_requests": self._web_search_requests,
            "web_search_cost": self._web_search_cost,
            "cache_creation_tokens": self._cache_creation_tokens,
            "cache_read_tokens": self._cache_read_tokens,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "stop_reason_counts": self._stop_reason_counts,
            "cpu_usage": self._cpu_usage,
            "memory_usage": self._memory_usage,
            # Enhanced compliance metrics
            "compliance": {
                "mode": compliance_status["compliance_mode"],
                "version": compliance_status["implementation_version"],
                "thinking_signature_rate": compliance_status["thinking_signature_preservation_rate"],
                "active_sessions": compliance_status["total_active_sessions"],
                "sessions_with_thinking": compliance_status["sessions_with_thinking"],
                "exact_preservation_enabled": True
            },
            "web_search_optimization": {
                "retention_turns": getattr(self, 'WEB_SEARCH_RESULT_RETENTION_TURNS', 1),
                "aggressive_cleanup": getattr(self, 'WEB_SEARCH_AGGRESSIVE_CLEANUP', True),
                "aggressive_caching": getattr(self, 'WEB_SEARCH_CACHE_AGGRESSIVE', True),
                "max_uses_optimized": self.WEB_SEARCH_MAX_USES == 1
            }
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
            
        # Add web search usage if any
        if stats.get('web_search_requests', 0) > 0:
            report += f"🔍 웹 검색: {stats['web_search_requests']:,}회 (${stats['web_search_cost']:.2f})\n"
            
        # Add cache performance if any cache activity
        cache_hits = stats.get('cache_hits', 0)
        cache_misses = stats.get('cache_misses', 0)
        if cache_hits > 0 or cache_misses > 0:
            cache_hit_rate = (cache_hits / (cache_hits + cache_misses)) * 100 if (cache_hits + cache_misses) > 0 else 0
            cache_read_tokens = stats.get('cache_read_tokens', 0)
            cache_creation_tokens = stats.get('cache_creation_tokens', 0)
            
            # Calculate approximate cache savings (90% cost reduction on cache hits)
            cache_savings_tokens = cache_read_tokens * 0.9  # 90% savings
            cache_savings_cost = (cache_savings_tokens / 1_000_000) * 3.0  # $3/MTok saved
            
            report += f"⚡ 캐시: 적중률 {cache_hit_rate:.1f}% ({cache_hits}/{cache_hits + cache_misses})\n"
            if cache_savings_cost > 0.001:  # Only show if savings > $0.001
                report += f"💰 캐시 절약: ${cache_savings_cost:.3f}\n"
            
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

    def _optimize_conversation_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Optimize conversation history by removing stale web search results based on retention settings
        
        Args:
            messages: Current conversation messages
            
        Returns:
            List[Dict[str, Any]]: Optimized messages with stale web search data removed
        """
        if len(messages) < 2:
            return messages
            
        # Get optimization settings with defaults
        retention_turns = getattr(self, 'WEB_SEARCH_RESULT_RETENTION_TURNS', 1)
        aggressive_cleanup = getattr(self, 'WEB_SEARCH_AGGRESSIVE_CLEANUP', True)
        
        if not aggressive_cleanup:
            # Use original conservative approach if aggressive cleanup is disabled
            retention_turns = 2  # Keep last 2 assistant messages (original behavior)
            
        optimized_messages = []
        assistant_message_count = 0
        total_web_search_blocks_removed = 0
        
        # Count assistant messages from the end to determine retention
        assistant_indices = []
        for i, message in enumerate(messages):
            if message.get("role") == "assistant":
                assistant_indices.append(i)
        
        # Determine which assistant messages should retain web search results
        messages_to_keep_search = set()
        if assistant_indices:
            # Keep web search results in the last N assistant messages based on retention_turns
            keep_count = min(retention_turns, len(assistant_indices))
            messages_to_keep_search.update(assistant_indices[-keep_count:])
        
        for i, message in enumerate(messages):
            if message.get("role") == "assistant":
                content = message.get("content", "")
                
                if isinstance(content, list):
                    # Check if this message contains web search results
                    has_web_search = any(
                        (hasattr(block, 'type') and block.type in ["web_search_tool_result", "server_tool_use"]) or
                        (isinstance(block, dict) and block.get("type") in ["web_search_tool_result", "server_tool_use"])
                        for block in content
                    )
                    
                    if has_web_search:
                        # Check if this message should retain web search results
                        should_keep_search = i in messages_to_keep_search
                        
                        if not should_keep_search:
                            # Remove web search tool results to reduce token usage
                            filtered_content = []
                            web_search_blocks_removed = 0
                            
                            for block in content:
                                block_type = getattr(block, 'type', None) or (block.get("type") if isinstance(block, dict) else None)
                                
                                if block_type in ["web_search_tool_result", "server_tool_use"]:
                                    web_search_blocks_removed += 1
                                    continue  # Skip web search blocks in older messages
                                else:
                                    # Keep text, thinking, and other important blocks
                                    filtered_content.append(block)
                            
                            if web_search_blocks_removed > 0:
                                total_web_search_blocks_removed += web_search_blocks_removed
                                logger.info(f"Removed {web_search_blocks_removed} web search blocks from message {i} "
                                          f"(retention: {retention_turns} turns)")
                                
                            # Only add the message if it still has content after filtering
                            if filtered_content:
                                optimized_message = message.copy()
                                optimized_message["content"] = filtered_content
                                optimized_messages.append(optimized_message)
                            else:
                                # If no content remains, skip this message entirely
                                logger.info(f"Skipping message {i} as it contained only web search data")
                        else:
                            # Keep messages within retention period with web search results
                            optimized_messages.append(message)
                    else:
                        # No web search data, keep as-is
                        optimized_messages.append(message)
                else:
                    # Simple string content, keep as-is
                    optimized_messages.append(message)
            else:
                # User messages, keep as-is
                optimized_messages.append(message)
        
        # Log optimization results
        original_count = len(messages)
        optimized_count = len(optimized_messages)
        if original_count != optimized_count or total_web_search_blocks_removed > 0:
            logger.info(f"Web search optimization: {original_count} → {optimized_count} messages, "
                       f"removed {total_web_search_blocks_removed} web search blocks "
                       f"(retention: {retention_turns} turns)")
            
        return optimized_messages 

    def get_compliance_status(self) -> Dict[str, Any]:
        """Get current compliance status and diagnostic information
        
        Returns:
            Dict[str, Any]: Compliance status and diagnostic data
        """
        total_sessions = len(self._chat_sessions)
        sessions_with_thinking = 0
        sessions_with_tools = 0
        total_thinking_blocks = 0
        total_thinking_with_signatures = 0
        
        # Analyze current chat sessions for compliance indicators
        for user_id, messages in self._chat_sessions.items():
            session_has_thinking = False
            session_has_tools = False
            
            for message in messages:
                if message.get("role") == "assistant":
                    content = message.get("content", "")
                    
                    if isinstance(content, list):
                        # Check for thinking and tool blocks in the content
                        for block in content:
                            if hasattr(block, 'type'):  # Anthropic content block object
                                if block.type == "thinking":
                                    session_has_thinking = True
                                    total_thinking_blocks += 1
                                    if hasattr(block, 'signature'):
                                        total_thinking_with_signatures += 1
                                elif block.type in ["server_tool_use", "web_search_tool_result"]:
                                    session_has_tools = True
                            elif isinstance(block, dict):  # Dict format
                                if block.get("type") == "thinking":
                                    session_has_thinking = True
                                    total_thinking_blocks += 1
                                    if "signature" in block:
                                        total_thinking_with_signatures += 1
                                elif block.get("type") in ["server_tool_use", "web_search_tool_result"]:
                                    session_has_tools = True
            
            if session_has_thinking:
                sessions_with_thinking += 1
            if session_has_tools:
                sessions_with_tools += 1
        
        # Calculate compliance metrics
        thinking_signature_rate = (total_thinking_with_signatures / total_thinking_blocks * 100) if total_thinking_blocks > 0 else 0
        
        return {
            "compliance_mode": "maximum",
            "implementation_version": "2025-01-extended-thinking-tools",
            "total_active_sessions": total_sessions,
            "sessions_with_thinking": sessions_with_thinking,
            "sessions_with_tools": sessions_with_tools,
            "thinking_blocks_total": total_thinking_blocks,
            "thinking_blocks_with_signatures": total_thinking_with_signatures,
            "thinking_signature_preservation_rate": thinking_signature_rate,
            "settings": {
                "thinking_enabled": self.THINKING_ENABLED,
                "thinking_budget": self.THINKING_BUDGET_TOKENS,
                "web_search_enabled": self.WEB_SEARCH_ENABLED,
                "prompt_caching_enabled": self.PROMPT_CACHING_ENABLED,
                "exact_content_preservation": True
            },
            "error_tracking": {
                "signature_validation_failures": 0,  # Would need to be tracked if we implement it
                "content_format_errors": 0,
                "recent_compliance_errors": []  # Would store recent compliance-related errors
            }
        }

    def validate_conversation_compliance(self, user_id: int) -> Dict[str, Any]:
        """Validate that a specific conversation maintains compliance standards
        
        Args:
            user_id: Discord user ID to validate
            
        Returns:
            Dict[str, Any]: Validation results and recommendations
        """
        if user_id not in self._chat_sessions:
            return {
                "status": "no_session",
                "compliant": True,
                "message": "No active session to validate"
            }
        
        messages = self._chat_sessions[user_id]
        issues = []
        warnings = []
        
        thinking_blocks_found = 0
        manual_reconstructions_detected = 0
        signature_preservation_count = 0
        
        for i, message in enumerate(messages):
            if message.get("role") == "assistant":
                content = message.get("content", "")
                
                if isinstance(content, list):
                    # Check each content block
                    for j, block in enumerate(content):
                        if hasattr(block, 'type'):  # Anthropic content block object (GOOD)
                            if block.type == "thinking":
                                thinking_blocks_found += 1
                                if hasattr(block, 'signature'):
                                    signature_preservation_count += 1
                                else:
                                    warnings.append(f"Message {i}, block {j}: Thinking block without signature")
                        elif isinstance(block, dict):  # Manual reconstruction (BAD for compliance)
                            if block.get("type") == "thinking":
                                thinking_blocks_found += 1
                                manual_reconstructions_detected += 1
                                issues.append(f"Message {i}, block {j}: Manually reconstructed thinking block detected")
                                if "signature" not in block:
                                    issues.append(f"Message {i}, block {j}: Missing signature in thinking block")
                                else:
                                    # This could be a legacy format
                                    warnings.append(f"Message {i}, block {j}: Dict-format thinking block with signature (legacy?)")
        
        # Determine compliance status
        is_compliant = len(issues) == 0
        signature_rate = (signature_preservation_count / thinking_blocks_found * 100) if thinking_blocks_found > 0 else 100
        
        result = {
            "status": "compliant" if is_compliant else "non_compliant",
            "compliant": is_compliant,
            "thinking_blocks_found": thinking_blocks_found,
            "signature_preservation_count": signature_preservation_count,
            "signature_preservation_rate": signature_rate,
            "manual_reconstructions": manual_reconstructions_detected,
            "issues": issues,
            "warnings": warnings,
            "recommendations": []
        }
        
        # Add recommendations based on findings
        if manual_reconstructions_detected > 0:
            result["recommendations"].append("Clear session and restart conversation to use exact preservation mode")
        if signature_rate < 100 and thinking_blocks_found > 0:
            result["recommendations"].append("Verify thinking block signature preservation in conversation storage")
        if len(warnings) > 0:
            result["recommendations"].append("Check for mixed legacy/compliance formats in conversation history")
            
        return result

    async def test_compliance_implementation(self) -> Dict[str, Any]:
        """Test the compliance implementation with a simple request
        
        Returns:
            Dict[str, Any]: Test results and compliance verification
        """
        try:
            logger.info("🧪 Testing maximum compliance implementation...")
            
            # Create a test conversation that should trigger thinking
            test_prompt = "복잡한 생태계 문제를 분석해줘: 기후 변화가 생물 다양성에 미치는 영향을 설명하고, 라인랩에서 할 수 있는 연구 방향을 제안해줘."
            test_user_id = 999999  # Special test user ID
            
            # Clear any existing test session
            if test_user_id in self._chat_sessions:
                del self._chat_sessions[test_user_id]
            
            # Run the test request
            response, sources = await self.chat(test_prompt, test_user_id)
            
            # Analyze the results
            compliance_validation = self.validate_conversation_compliance(test_user_id)
            
            # Clean up test session
            if test_user_id in self._chat_sessions:
                del self._chat_sessions[test_user_id]
            
            test_results = {
                "test_status": "completed",
                "response_generated": bool(response),
                "sources_provided": bool(sources),
                "compliance_validation": compliance_validation,
                "implementation_working": compliance_validation.get("compliant", False),
                "test_summary": {
                    "thinking_blocks_preserved": compliance_validation.get("thinking_blocks_found", 0) > 0,
                    "signatures_preserved": compliance_validation.get("signature_preservation_rate", 0) == 100,
                    "manual_reconstructions_avoided": compliance_validation.get("manual_reconstructions", 0) == 0
                }
            }
            
            logger.info(f"✅ Compliance test completed: {'PASSED' if test_results['implementation_working'] else 'FAILED'}")
            return test_results
            
        except Exception as e:
            logger.error(f"❌ Compliance test failed: {e}")
            return {
                "test_status": "failed",
                "error": str(e),
                "implementation_working": False,
                "test_summary": {
                    "error_type": type(e).__name__,
                    "compliance_risk": "high" if "signature" in str(e).lower() else "medium"
                }
            }