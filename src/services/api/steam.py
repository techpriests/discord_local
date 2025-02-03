import logging
from typing import Optional, Tuple, List, Dict, Any, cast
import time
import re

import aiohttp
from src.services.api.base import BaseAPI, RateLimitConfig
from src.utils.api_types import GameInfo

logger = logging.getLogger(__name__)

class SteamAPI(BaseAPI[GameInfo]):
    """Steam API client implementation"""

    SEARCH_URL = "https://store.steampowered.com/api/storesearch"
    PLAYER_COUNT_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
    PLAYER_HISTORY_URL = "https://steamcharts.com/app/{}/chart-data.json"

    def __init__(self, api_key: str) -> None:
        """Initialize Steam API client
        
        Args:
            api_key: Steam Web API key
        """
        super().__init__(api_key)
        self._rate_limits = {
            "search": RateLimitConfig(30, 60),  # 30 requests per minute
            "player_count": RateLimitConfig(60, 60),  # 60 requests per minute
            "player_history": RateLimitConfig(20, 60),  # 20 requests per minute for historical data
            "details": RateLimitConfig(150, 300),  # 150 requests per 5 minutes
        }

    def _calculate_similarity(self, query: str, game_name: str) -> float:
        """Calculate similarity between query and game name
        
        Args:
            query: Search query
            game_name: Game name to compare

        Returns:
            float: Similarity score (0-100)
        """
        # Convert both to lowercase for case-insensitive comparison
        query = query.lower()
        game_name = game_name.lower()

        # Exact match
        if query == game_name:
            return 100.0

        # Check if query is a substring of game name
        if query in game_name:
            return 90.0

        # Check if game name contains all characters from query in order
        query_chars = list(query)
        game_chars = list(game_name)
        i = 0
        j = 0
        matches = 0
        while i < len(query_chars) and j < len(game_chars):
            if query_chars[i] == game_chars[j]:
                matches += 1
                i += 1
            j += 1
        
        if matches == len(query_chars):
            return 80.0

        # Calculate character match ratio
        match_ratio = matches / len(query_chars)
        return match_ratio * 70.0

    async def validate_credentials(self) -> bool:
        """Validate Steam API key
        
        Returns:
            bool: True if credentials are valid
        """
        try:
            # Test with CS:GO app id
            await self.get_player_count(730)
            return True
        except Exception as e:
            logger.error(f"Steam API key validation failed: {e}")
            return False

    async def find_game(
        self, 
        name: str,
        include_history: bool = False
    ) -> Tuple[Optional[GameInfo], float, Optional[List[GameInfo]]]:
        """Find game by name
        
        Args:
            name: Game name to search
            include_history: Whether to include player count history data

        Returns:
            Tuple containing:
            - GameInfo or None: Best match game info (game with most players among top matches)
            - float: Match similarity score (0-100)
            - List[GameInfo] or None: Similar games list (always None)

        Raises:
            ValueError: If search fails
        """
        try:
            params = {
                "term": name,
                "l": "korean",
                "cc": "KR",
                "infinite": 1,
                "json": 1,
            }

            data = await self._make_request(
                self.SEARCH_URL, 
                params=params,
                endpoint="search"
            )

            if not data or "items" not in data or not data["items"]:
                return None, 0, None

            # First, get player counts for all candidates to find the most active game
            candidates = []
            for item in data["items"][:5]:  # Only process top 5 matches
                try:
                    app_id = item["id"]
                    current_players = await self.get_player_count(app_id)
                    
                    # Calculate match score
                    similarity = 100.0 if item["name"].lower() == name.lower() else 50.0
                    
                    # Only include games with players or exact name matches
                    if current_players > 0 or similarity == 100.0:
                        candidates.append((item, current_players, similarity))

                except Exception as e:
                    logger.error(f"Error getting player count for {item.get('name', 'Unknown')}: {e}")
                    continue

            if not candidates:
                return None, 0, None

            # Sort by player count (primary) and similarity (secondary)
            candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
            
            # Only get history for the best match
            best_item, current_players, similarity = candidates[0]
            
            try:
                history = await self.get_player_history(best_item["id"], include_history)
                
                game_info = GameInfo(
                    name=best_item["name"],
                    player_count=current_players,
                    peak_24h=history["peak_24h"],
                    image_url=best_item.get("tiny_image") or best_item.get("large_capsule_image")
                )
                
                return game_info, similarity, None

            except Exception as e:
                logger.error(f"Error getting history for {best_item.get('name', 'Unknown')}: {e}")
                return None, 0, None

        except Exception as e:
            logger.error(f"Error in find_game for query '{name}': {e}")
            raise ValueError(f"게임 검색에 실패했습니다: {str(e)}") from e

    async def get_player_count(self, app_id: int) -> int:
        """Get current player count for game
        
        Args:
            app_id: Steam app ID

        Returns:
            int: Current player count

        Raises:
            ValueError: If request fails
        """
        try:
            params = {
                "appid": app_id,
                "key": self.api_key
            }

            data = await self._make_request(
                self.PLAYER_COUNT_URL,
                params=params,
                endpoint="player_count"
            )

            if not data or "response" not in data:
                raise ValueError("Invalid response format")

            player_count = data["response"].get("player_count")
            if player_count is None:
                raise ValueError("Player count not found in response")

            return cast(int, player_count)

        except Exception as e:
            logger.error(f"Error getting player count for app {app_id}: {e}")
            return 0  # Return 0 for failed requests

    async def get_player_history(self, app_id: int, include_history: bool = False) -> Dict[str, Any]:
        """Get historical player count data for game
        
        Args:
            app_id: Steam app ID
            include_history: Whether to include full history data

        Returns:
            Dict containing:
            - peak_24h: Peak players in last 24 hours
            - history: List of (timestamp, player_count) tuples (only if include_history=True)

        Raises:
            ValueError: If request fails
        """
        try:
            url = self.PLAYER_HISTORY_URL.format(app_id)
            
            # Get last 24 hours of data
            day_ago = int(time.time() - 24 * 3600)
            url = f"{url}?from={day_ago}"
            
            data = await self._make_request(
                url,
                endpoint="player_history"
            )

            if not data:
                return {
                    "peak_24h": 0,
                    "history": [] if include_history else None
                }

            # Find peak in last 24 hours
            peak_24h = 0
            now = time.time()
            day_ago = now - 24 * 3600
            
            # Process data in chronological order
            for timestamp, count in sorted(data, key=lambda x: x[0]):
                if count is not None and timestamp >= day_ago:
                    peak_24h = max(peak_24h, count)

            return {
                "peak_24h": peak_24h,
                "history": data if include_history else None
            }

        except Exception as e:
            logger.error(f"Error getting player history for app {app_id}: {e}")
            return {
                "peak_24h": 0,
                "history": [] if include_history else None
            }

    async def close(self) -> None:
        """Cleanup resources"""
        await super().close()
