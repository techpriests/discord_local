import logging
from typing import Optional, Tuple, List, Dict, Any, cast

import aiohttp
from src.services.api.base import BaseAPI, RateLimitConfig
from src.utils.api_types import GameInfo

logger = logging.getLogger(__name__)

class SteamAPI(BaseAPI[GameInfo]):
    """Steam API client implementation"""

    SEARCH_URL = "https://store.steampowered.com/api/storesearch"
    PLAYER_COUNT_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"

    def __init__(self, api_key: str) -> None:
        """Initialize Steam API client
        
        Args:
            api_key: Steam Web API key
        """
        super().__init__(api_key)
        self._rate_limits = {
            "search": RateLimitConfig(30, 60),  # 30 requests per minute
            "player_count": RateLimitConfig(60, 60),  # 60 requests per minute
            "details": RateLimitConfig(150, 300),  # 150 requests per 5 minutes
        }

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
        name: str
    ) -> Tuple[Optional[GameInfo], float, Optional[List[GameInfo]]]:
        """Find game by name
        
        Args:
            name: Game name to search

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

            games: List[GameInfo] = []
            for item in data["items"]:
                try:
                    game_info = GameInfo(
                        name=item["name"],
                        player_count=await self.get_player_count(item["id"])
                    )
                    games.append(game_info)
                except Exception as e:
                    logger.error(f"Error processing game {item.get('name', 'Unknown')}: {e}")
                    continue

                # Only get player count for top 5 results
                if len(games) >= 5:
                    break

            if not games:
                return None, 0, None

            # Calculate similarity score (simplified)
            similarity = 100.0 if games[0]["name"].lower() == name.lower() else 50.0
            
            return games[0], similarity, games[1:] if len(games) > 1 else None

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

    async def close(self) -> None:
        """Cleanup resources"""
        await super().close()
