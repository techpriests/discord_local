import aiohttp
from typing import Dict, Optional, Tuple, List, TypedDict, Literal, Union, Any
from fuzzywuzzy import fuzz
import time
from collections import defaultdict
import asyncio
import json
import os
from datetime import datetime, timezone
import re
import logging

# Add proper logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LocalizedName(TypedDict):
    name: str
    language: str

class GameInfo(TypedDict):
    appid: int
    name: str  # English name
    names: Dict[Literal['koreana', 'japanese', 'schinese', 'tchinese'], LocalizedName]
    player_count: Optional[int]
    is_dlc: bool
    type: str
    categories: List[str]

class APIError(Exception):
    """Base exception for all API errors"""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error

class RateLimitError(APIError):
    def __init__(self, endpoint: str, wait_time: float, original_error: Optional[Exception] = None):
        super().__init__(
            f"Rate limit exceeded for {endpoint}. Try again in {wait_time:.1f} seconds.",
            original_error
        )
        self.endpoint = endpoint
        self.wait_time = wait_time

class NetworkError(APIError):
    """Network-related errors"""
    pass

class ValidationError(APIError):
    """Data validation errors"""
    pass

class APIService:
    """Service for handling API requests to Steam, Weather, and other services"""
    
    LANGUAGES = {
        'koreana': {
            'range': ('\uac00', '\ud7a3'),
            'name': '한국어',
            'cc': 'KR',
            'weight': 1.0
        },
        'japanese': {
            'range': ('\u3040', '\u30ff'),
            'name': '日本語',
            'cc': 'JP',
            'weight': 0.9
        },
        'schinese': {
            'range': ('\u4e00', '\u9fff'),
            'name': '简体中文',
            'cc': 'CN',
            'extra_check': lambda c: '\u4e00' <= c <= '\u9fff' and ord(c) < 0x8000,
            'weight': 0.9
        },
        'tchinese': {
            'range': ('\u4e00', '\u9fff'),
            'name': '繁體中文',
            'cc': 'TW',
            'extra_check': lambda c: '\u4e00' <= c <= '\u9fff' and ord(c) >= 0x8000,
            'weight': 0.9
        }
    }
    
    # Rate limiting configurations
    RATE_LIMITS = {
        'steam_search': {'requests': 30, 'period': 60, 'backoff_factor': 1.5},
        'steam_charts': {'requests': 10, 'period': 60, 'backoff_factor': 2.0},
        'steam_player_count': {'requests': 60, 'period': 60, 'backoff_factor': 1.5},
        'steam_app_list': {'requests': 10, 'period': 60, 'backoff_factor': 2.0},
        'steam_details': {'requests': 150, 'period': 300, 'backoff_factor': 1.5},
        'weather': {'requests': 60, 'period': 60, 'backoff_factor': 1.2},
        'population': {'requests': 30, 'period': 60, 'backoff_factor': 1.2},
        'exchange_rate': {'requests': 60, 'period': 60, 'backoff_factor': 1.2},
    }
    
    STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch"
    
    EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/KRW"  # Free API, no key needed
    
    def __init__(self, weather_key: str, steam_key: str):
        self.weather_key = weather_key
        self.steam_key = steam_key
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting state
        self.rate_limits = defaultdict(list)
        self.backoff_times: Dict[str, float] = {}
    
    async def _cleanup_rate_limits(self) -> None:
        """Clean up expired rate limit data"""
        current_time = time.time()
        for endpoint, config in self.RATE_LIMITS.items():
            # Clean up old timestamps
            self.rate_limits[endpoint] = [
                (ts, count) for ts, count in self.rate_limits[endpoint]
                if current_time - ts <= config['period']
            ]
            # Clean up expired backoff times
            if endpoint in self.backoff_times and current_time > self.backoff_times[endpoint]:
                del self.backoff_times[endpoint]

    async def _check_rate_limit(self, endpoint: str) -> bool:
        """Enhanced rate limit checking"""
        try:
            await self._cleanup_rate_limits()
            
            config = self.RATE_LIMITS.get(endpoint)
            if not config:
                return True
                
            current_time = time.time()
            
            # Check backoff
            if endpoint in self.backoff_times:
                wait_time = self.backoff_times[endpoint] - current_time
                if wait_time > 0:
                    raise RateLimitError(endpoint, wait_time, None)
            
            # Calculate current usage
            window_start = current_time - config['period']
            total_requests = sum(
                count for ts, count in self.rate_limits[endpoint]
                if ts > window_start
            )
            
            if total_requests >= config['requests']:
                backoff_time = config['period'] / config['requests'] * config['backoff_factor']
                self.backoff_times[endpoint] = current_time + backoff_time
                raise RateLimitError(endpoint, backoff_time, None)
            
            self.rate_limits[endpoint].append((current_time, 1))
            return True
            
        except RateLimitError:
            raise
        except Exception as e:
            raise APIError(f"Rate limit check failed: {str(e)}", e)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def _get_with_retry(
        self, 
        url: str, 
        params: Optional[Dict] = None, 
        endpoint: str = None,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        timeout: float = 10.0
    ) -> Dict:
        """Make API request with retry mechanism"""
        delay = initial_delay
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if endpoint:
                    await self._check_rate_limit(endpoint)
                    
                session = await self._get_session()
                async with session.get(
                    url, 
                    params=params, 
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Too Many Requests
                        retry_after = float(response.headers.get('Retry-After', 60))
                        raise RateLimitError(endpoint or 'unknown', retry_after, None)
                    elif response.status >= 500:
                        raise NetworkError(f"Server error: {response.status}")
                    else:
                        raise APIError(f"API call failed: {response.status} for URL: {url}")
                        
            except RateLimitError as e:
                logger.warning(f"Rate limit hit on attempt {attempt + 1}, waiting {e.wait_time}s...")
                await asyncio.sleep(e.wait_time)
                delay = e.wait_time * 1.5
                last_error = e
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                last_error = NetworkError("Request timed out")
            except Exception as e:
                logger.error(f"Request failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                last_error = e
        
        raise last_error or APIError("Max retries exceeded")
    
    # Weather API
    async def get_weather(self, city: str) -> Dict:
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": city,
            "appid": self.weather_key,
            "units": "metric",
            "lang": "kr"
        }
        return await self._get_with_retry(url, params)
    
    # Steam API
    async def _get_app_details(self, app_id: int, language: str = 'english') -> Optional[Dict]:
        """Get detailed app information from Steam store API"""
        try:
            url = "https://store.steampowered.com/api/appdetails"
            params = {
                'appids': app_id,
                'l': language,
                'cc': self.LANGUAGES.get(language, {}).get('cc', 'US')
            }
            
            data = await self._get_with_retry(url, params=params, endpoint='steam_details')
            if str(app_id) in data and data[str(app_id)]['success']:
                return data[str(app_id)]['data']
            return None
        except Exception as e:
            logger.error(f"Error getting app details for {app_id}: {e}")
            return None

    def _find_base_game(self, games: List[GameInfo]) -> List[GameInfo]:
        """Filter out DLCs and find base games using multiple checks"""
        if not games:
            return []
            
        def is_dlc(game: GameInfo) -> bool:
            name = game['name'].lower()
            type_info = game.get('type', '').lower()
            categories = game.get('categories', [])
            
            # Check if it's explicitly marked as DLC
            if type_info == 'dlc' or game.get('is_dlc', False):
                return True
                
            # Check if it's in the DLC category
            if 'DLC' in categories:
                return True
                
            # Check name patterns for DLC/editions
            dlc_patterns = [
                ' dlc',
                'season pass',
                'expansion',
                'content pack',
                'soundtrack',
                'artbook',
                'bonus content',
                'complete edition',
                'deluxe edition',
                'ultimate edition',
                'digital edition',
                'collector\'s edition',
                'definitive edition',
                'bundle',
                ' pack' # space before to avoid false positives
            ]
            
            return any(pattern in name for pattern in dlc_patterns)
        
        # Filter out DLCs and special editions
        base_games = [game for game in games if not is_dlc(game)]
        
        # If we filtered out everything, return the original first result
        return base_games if base_games else [games[0]]

    async def search_steam_games(self, query: str, language: str = 'english') -> List[GameInfo]:
        """Search games using Steam store search API with localization support"""
        try:
            params = {
                'term': query,
                'l': language,
                'category1': 998,  # Games only
                'cc': self.LANGUAGES.get(language, {}).get('cc', 'US'),
                'supportedlang': language,
                'infinite': 1,
                'json': 1
            }
            
            data = await self._get_with_retry(
                self.STEAM_SEARCH_URL, 
                params=params,
                endpoint='steam_search'
            )
            
            if not data or 'items' not in data:
                return []
                
            games: List[GameInfo] = []
            for item in data['items']:
                try:
                    # Get detailed app info to check if it's DLC
                    details = await self._get_app_details(item['id'], language)
                    
                    names = {}
                    if language != 'english':
                        names[language] = {
                            'name': item['name'],
                            'language': self.LANGUAGES.get(language, {}).get('name', language)
                        }
                    
                    game_info: GameInfo = {
                        'appid': item['id'],
                        'name': item['name'],
                        'names': names,
                        'player_count': None,
                        'is_dlc': details.get('type', '').lower() == 'dlc' if details else False,
                        'type': details.get('type', '') if details else item.get('type', ''),
                        'categories': details.get('categories', []) if details else []
                    }
                    
                    # Get player count for top results
                    if len(games) < 5:
                        try:
                            player_count = await self.get_player_count(item['id'])
                            game_info['player_count'] = player_count
                        except Exception as e:
                            logger.error(f"Could not get player count for {item['name']}: {e}")
                    
                    games.append(game_info)
                except Exception as e:
                    logger.error(f"Error processing search result: {e}")
                    continue
            
            # Filter games to find base game
            return self._find_base_game(games)
            
        except Exception as e:
            logger.error(f"Error searching Steam games: {e}")
            return []

    async def find_game(self, game_name: str) -> Tuple[Optional[GameInfo], float, Optional[List[GameInfo]]]:
        """Search for a game by name in any supported language"""
        try:
            search_name = game_name.lower().strip()[:50]
            detected_langs = self.detect_languages(search_name)
            
            logger.info(f"Searching for game: '{game_name}' (detected languages: {', '.join(detected_langs) or 'english'})")
            
            # Search in detected language first
            primary_lang = detected_langs[0] if detected_langs else 'english'
            games = await self.search_steam_games(search_name, primary_lang)
            
            if not games:
                # Try English if no results in primary language
                if primary_lang != 'english':
                    games = await self.search_steam_games(search_name, 'english')
            
            if not games:
                logger.info(f"No matches found for query: '{game_name}'")
                return None, 0, None
            
            # Return best match and similar matches
            best_match = games[0]
            similar_matches = games[1:5] if len(games) > 1 else None
            
            return best_match, 100, similar_matches
            
        except Exception as e:
            logger.error(f"Steam API Error in find_game for query '{game_name}': {e}")
            raise

    async def get_player_count(self, app_id: int) -> int:
        """Get current player count for a game"""
        try:
            url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={app_id}"
            data = await self._get_with_retry(url, endpoint='steam_player_count')
            return data['response']['player_count']
        except Exception as e:
            logger.error(f"Steam API Error in get_player_count: {e}")
            raise
    
    # Population API
    async def get_country_info(self, country_name: str) -> Dict:
        url = f"https://restcountries.com/v3.1/name/{country_name}"
        data = await self._get_with_retry(url)
        return data[0]
    
    async def close(self):
        """Close the session and cleanup"""
        try:
            if self.session:
                await self.session.close()
        except Exception as e:
            logger.error(f"Error closing service: {e}")
        finally:
            self.session = None
    
    def detect_languages(self, text: str) -> List[str]:
        """Detect languages in text based on character ranges
        
        Args:
            text: The text to analyze
            
        Returns:
            List of detected language codes
        """
        return [
            lang for lang, info in self.LANGUAGES.items()
            if any(info['range'][0] <= c <= info['range'][1] for c in text)
        ]

    async def get_exchange_rates(self) -> Dict[str, float]:
        """Get exchange rates for KRW to various currencies
        
        Returns:
            Dict with currency codes as keys and exchange rates as values
            Example: {'USD': 0.00075, 'EUR': 0.00070, 'JPY': 0.11}
        """
        try:
            data = await self._get_with_retry(
                self.EXCHANGE_RATE_URL,
                endpoint='exchange_rate'
            )
            
            if not data or 'rates' not in data:
                raise APIError("Failed to get exchange rates")
                
            # Get rates for common currencies
            rates = {
                'USD': 1 / data['rates']['USD'],  # Convert to KRW->USD rate
                'EUR': 1 / data['rates']['EUR'],
                'JPY': 1 / data['rates']['JPY'],
                'CNY': 1 / data['rates']['CNY'],
                'GBP': 1 / data['rates']['GBP'],
                'AUD': 1 / data['rates']['AUD'],
                'CAD': 1 / data['rates']['CAD'],
                'HKD': 1 / data['rates']['HKD'],
                'SGD': 1 / data['rates']['SGD'],
                'TWD': 1 / data['rates']['TWD']
            }
            
            return rates
            
        except Exception as e:
            logger.error(f"Error getting exchange rates: {e}")
            raise APIError(f"Failed to get exchange rates: {str(e)}")

    async def get_player_history(self, app_id: int) -> Dict:
        """Get historical player data for a game"""
        try:
            url = f"https://steamcharts.com/app/{app_id}/chart-data.json"
            data = await self._get_with_retry(url, endpoint='steam_charts')
            
            if not data:
                return None
            
            # Get last 7 days of data
            recent_data = data[-7:]
            
            # Calculate peak and average
            peak_players = max(point[1] for point in recent_data)
            avg_players = sum(point[1] for point in recent_data) // len(recent_data)
            
            return {
                'peak_7d': peak_players,
                'avg_7d': avg_players,
                'trend': recent_data[-1][1] - recent_data[0][1]  # Positive means growing
            }
        except Exception as e:
            logger.error(f"Error getting player history for {app_id}: {e}")
            return None 