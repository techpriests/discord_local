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
            - GameInfo or None: Best match game info
            - float: Match similarity score (0-100)
            - List[GameInfo] or None: Similar games list

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

            if not data or "items" not in data:
                return None, 0, None

            games: List[Tuple[GameInfo, float]] = []
            for item in data["items"]:
                try:
                    app_id = item["id"]
                    current_players = await self.get_player_count(app_id)
                    history = await self.get_player_history(app_id, include_history)
                    
                    game_info = GameInfo(
                        name=item["name"],
                        player_count=current_players,
                        peak_24h=history["peak_24h"],
                        peak_7d=history["peak_7d"],
                        avg_7d=history["avg_7d"],
                        history=history.get("history"),
                        image_url=item.get("tiny_image") or item.get("large_capsule_image")
                    )
                    
                    # Calculate similarity score for this game
                    similarity = self._calculate_similarity(name, item["name"])
                    games.append((game_info, similarity))

                except Exception as e:
                    logger.error(f"Error processing game {item.get('name', 'Unknown')}: {e}")
                    continue

                # Only get player count for top 5 results
                if len(games) >= 5:
                    break

            if not games:
                return None, 0, None

            # Sort games by similarity score
            games.sort(key=lambda x: x[1], reverse=True)
            
            # Return best match and other games
            best_match, best_score = games[0]
            other_games = [game for game, _ in games[1:]] if len(games) > 1 else None
            
            return best_match, best_score, other_games

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
            - peak_7d: Peak players in last 7 days
            - avg_7d: Average players in last 7 days
            - history: List of (timestamp, player_count) tuples (only if include_history=True)
            - peak_all: All-time peak players (only if include_history=True)

        Raises:
            ValueError: If request fails
        """
        try:
            url = self.PLAYER_HISTORY_URL.format(app_id)
            
            # For regular command, only get last 7 days of data
            # For chart command, get full history
            if not include_history:
                # Add timestamp parameter to only get recent data
                week_ago = int(time.time() - 7 * 24 * 3600)
                url = f"{url}?from={week_ago}"
            
            data = await self._make_request(
                url,
                endpoint="player_history"
            )

            if not data:
                return {
                    "peak_24h": 0,
                    "peak_7d": 0,
                    "avg_7d": 0.0,
                    "history": [] if include_history else None,
                    "peak_all": 0 if include_history else None
                }

            # Data is returned as a list of [timestamp, player_count] pairs
            now = time.time()
            day_ago = now - 24 * 3600  # 24 hours ago
            week_ago = now - 7 * 24 * 3600  # 7 days ago
            three_months_ago = now - 90 * 24 * 3600  # 90 days ago
            
            counts_7d = []
            peak_24h = 0
            peak_7d = 0
            peak_all = 0 if include_history else None
            
            # For history, keep hourly data points from last 3 months
            filtered_history = []
            last_hour = 0
            
            for entry in data:
                timestamp, count = entry
                if count is not None:
                    if include_history:
                        peak_all = max(peak_all, count)  # Track all-time peak only for chart command
                    
                    if timestamp >= week_ago:
                        counts_7d.append(count)
                        peak_7d = max(peak_7d, count)
                        if timestamp >= day_ago:
                            peak_24h = max(peak_24h, count)
                
                # If including history, filter to hourly points for last 3 months
                if include_history and timestamp >= three_months_ago:
                    current_hour = int(timestamp / 3600)
                    if current_hour > last_hour:  # Only keep one point per hour
                        filtered_history.append((timestamp, count))
                        last_hour = current_hour

            avg_7d = sum(counts_7d) / len(counts_7d) if counts_7d else 0.0

            return {
                "peak_24h": peak_24h,
                "peak_7d": peak_7d,
                "avg_7d": avg_7d,
                "history": filtered_history if include_history else None,
                "peak_all": peak_all if include_history else None
            }

        except Exception as e:
            logger.error(f"Error getting player history for app {app_id}: {e}")
            return {
                "peak_24h": 0,
                "peak_7d": 0,
                "avg_7d": 0.0,
                "history": [] if include_history else None,
                "peak_all": 0 if include_history else None
            }

    async def close(self) -> None:
        """Cleanup resources"""
        await super().close()
