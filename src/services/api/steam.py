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
    STORE_PAGE_URL = "https://store.steampowered.com/app/{}"

    def __init__(self, api_key: str) -> None:
        """Initialize Steam API client
        
        Args:
            api_key: Steam Web API key
        """
        super().__init__(api_key)
        self._rate_limits = {
            "search": RateLimitConfig(30, 60),  # 30 requests per minute
            "player_count": RateLimitConfig(60, 60),  # 60 requests per minute
            "store": RateLimitConfig(20, 60),  # 20 requests per minute for store page
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
        """Find game by name"""
        try:
            logger.info(f"Searching for game: {name}")
            params = {
                "term": name,
                "l": "koreana",
                "cc": "KR",
                "category1": "998",
                "supportedlang": "koreana",
                "json": 1,
            }
            logger.debug(f"Search parameters: {params}")

            data = await self._make_request(
                self.SEARCH_URL, 
                params=params,
                endpoint="search"
            )
            logger.debug(f"Initial Korean search response: {data}")

            if not data or "items" not in data or not data["items"]:
                logger.info("No results with Korean language, trying English search")
                params["l"] = "english"
                params.pop("supportedlang", None)
                data = await self._make_request(
                    self.SEARCH_URL,
                    params=params,
                    endpoint="search"
                )
                logger.debug(f"English search response: {data}")
                if not data or "items" not in data or not data["items"]:
                    logger.warning(f"No games found for query: {name}")
                    return None, 0, None

            games: List[GameInfo] = []
            logger.info(f"Found {len(data['items'])} potential matches")
            
            for i, item in enumerate(data["items"]):
                try:
                    app_id = item.get("id")
                    logger.debug(f"Processing game {i+1}: ID={app_id}, Name={item.get('name', 'Unknown')}")
                    
                    current_players = await self.get_player_count(app_id)
                    logger.info(f"Current players for {item.get('name')}: {current_players}")
                    
                    peak_24h = 0
                    if i == 0:
                        logger.debug("Getting history for first match")
                        history = await self.get_player_history(app_id, include_history)
                        peak_24h = history["peak_24h"]
                        logger.info(f"24h peak for {item.get('name')}: {peak_24h}")
                    
                    game_name = item.get("name", "")
                    if "name_korean" in item:
                        logger.debug(f"Found Korean name (name_korean): {item['name_korean']}")
                        game_name = item["name_korean"]
                    elif "korean_name" in item:
                        logger.debug(f"Found Korean name (korean_name): {item['korean_name']}")
                        game_name = item["korean_name"]
                    else:
                        logger.debug(f"No Korean name found, using English name: {game_name}")
                    
                    game_info = GameInfo(
                        name=game_name,
                        player_count=current_players,
                        peak_24h=peak_24h,
                        image_url=item.get("tiny_image") or item.get("large_capsule_image")
                    )
                    logger.debug(f"Created game info: {game_info}")
                    games.append(game_info)
                except Exception as e:
                    logger.error(f"Error processing game {item.get('name', 'Unknown')}: {e}", exc_info=True)
                    continue

                if len(games) >= 3:
                    logger.debug("Reached maximum of 3 games, stopping search")
                    break

            if not games:
                logger.warning("No valid games found after processing")
                return None, 0, None

            best_match = max(games, key=lambda g: g["player_count"])
            logger.info(f"Best match: {best_match['name']} with {best_match['player_count']} players")
            
            other_games = [g for g in games if g != best_match]
            if other_games:
                logger.debug(f"Similar games: {[g['name'] for g in other_games]}")
            
            similarity = 100.0 if best_match["name"].lower() == name.lower() else 50.0
            logger.debug(f"Similarity score: {similarity}")
            
            return best_match, similarity, other_games if other_games else None

        except Exception as e:
            logger.error(f"Error in find_game for query '{name}': {e}", exc_info=True)
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
            url = self.STORE_PAGE_URL.format(app_id)
            
            # Add special headers to avoid age check redirects
            headers = {
                "Cookie": "birthtime=0; mature_content=1",
                "User-Agent": "Mozilla/5.0"
            }
            
            data = await self._make_request(
                url,
                endpoint="store",
                headers=headers,
                raw_text=True  # Get raw HTML response
            )

            if not data:
                return {
                    "peak_24h": 0,
                    "history": [] if include_history else None
                }

            # Extract peak players from the store page HTML
            # The data is typically in a div with class "player_count_row"
            import re
            peak_match = re.search(r'24-hour peak:\s*([0-9,]+)', data)
            peak_24h = 0
            if peak_match:
                peak_str = peak_match.group(1).replace(',', '')
                peak_24h = int(peak_str)

            return {
                "peak_24h": peak_24h,
                "history": [] if include_history else None
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
