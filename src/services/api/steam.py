import logging
from typing import List, Optional, Tuple, TypedDict

from .base import BaseAPI, RateLimitConfig

logger = logging.getLogger(__name__)

# API URLs
STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch"
STEAM_PLAYER_COUNT_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)


class GameInfo(TypedDict):
    """Type definition for game information"""

    appid: int
    name: str
    type: str
    player_count: Optional[int]


class SteamAPI(BaseAPI):
    """Steam API client implementation."""

    def __init__(self, api_key: str):
        """Initialize Steam API client.
        
        Args:
            api_key: Steam Web API key
        """
        super().__init__()
        self._api_key = api_key
        self._rate_limits = {
            "search": RateLimitConfig(30, 60),  # 30 requests per minute
            "player_count": RateLimitConfig(60, 60),  # 60 requests per minute
            "details": RateLimitConfig(150, 300),  # 150 requests per 5 minutes
        }

    @property
    def api_key(self) -> str:
        """Get Steam API key."""
        return self._api_key

    async def initialize(self) -> None:
        """Initialize Steam API resources"""
        pass

    async def validate_credentials(self) -> bool:
        """Validate Steam API key"""
        try:
            await self.get_player_count(730)  # Test with CS:GO app id
            return True
        except Exception as e:
            logger.error(f"Steam API key validation failed: {e}")
            return False

    async def get_player_count(self, app_id: int) -> int:
        """Get current player count for a game

        Args:
            app_id: Steam application ID

        Returns:
            int: Current number of players

        Raises:
            ValueError: If app_id is invalid
            Exception: If API request fails
        """
        try:
            params = {"appid": app_id, "key": self.api_key}
            data = await self._get_with_retry(STEAM_PLAYER_COUNT_URL, params, "player_count")

            if not data or "response" not in data or "player_count" not in data["response"]:
                raise ValueError(f"Invalid response for app_id: {app_id}")

            return data["response"]["player_count"]
        except Exception as e:
            raise ValueError(f"Failed to get player count: {e}") from e

    async def find_game(
        self, name: str
    ) -> Tuple[Optional[GameInfo], float, Optional[List[GameInfo]]]:
        """Search for a game by name"""
        try:
            params = {
                "term": name,
                "l": "english",
                "category1": 998,  # Games only
                "cc": "US",
                "supportedlang": "english",
                "infinite": 1,
                "json": 1,
            }

            data = await self._get_with_retry(STEAM_SEARCH_URL, params=params, endpoint="search")

            if not data or "items" not in data:
                return None, 0, None

            games: List[GameInfo] = []
            for item in data["items"]:
                try:
                    game_info: GameInfo = {
                        "appid": item["id"],
                        "name": item["name"],
                        "type": item.get("type", ""),
                        "player_count": None,
                    }

                    # Get player count for top results
                    if len(games) < 5:
                        try:
                            player_count = await self.get_player_count(item["id"])
                            game_info["player_count"] = player_count
                        except Exception as e:
                            logger.error(f"Could not get player count for {item['name']}: {e}")

                    games.append(game_info)
                except Exception as e:
                    logger.error(f"Error processing search result: {e}")
                    continue

            if not games:
                return None, 0, None

            # Return best match and similar matches
            return games[0], 100, games[1:5] if len(games) > 1 else None

        except Exception as e:
            logger.error(f"Steam API Error in find_game for query '{name}': {e}")
            raise

    async def close(self):
        """Cleanup resources"""
        await super().close()
