import aiohttp
from typing import Dict, Optional, Tuple, List
from fuzzywuzzy import fuzz
import time
from collections import defaultdict
import asyncio
import json
import os
from datetime import datetime, timedelta

class APIService:
    def __init__(self, weather_key: str, steam_key: str):
        self.weather_key = weather_key
        self.steam_key = steam_key
        self.session = None
        # Rate limiting: {endpoint: [(timestamp, request_count)]}
        self.rate_limits = defaultdict(list)
        # Configure rate limits for different endpoints
        self.rate_configs = {
            'steam_player_count': {'requests': 60, 'period': 60},
            'steam_app_list': {'requests': 10, 'period': 60},
            'steam_details': {'requests': 200, 'period': 300},  # 200 requests per 5 minutes
            'weather': {'requests': 60, 'period': 60},
            'population': {'requests': 30, 'period': 60},
        }
        self.cache_file = 'data/steam_games.json'
        self.cache_duration = timedelta(days=1)  # Update cache every day
        self.korean_names_cache = {}
        self.korean_names_file = 'data/korean_names.json'
        
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        self._load_korean_names_cache()
    
    async def _check_rate_limit(self, endpoint: str) -> bool:
        """Check if we're within rate limits for the endpoint"""
        config = self.rate_configs.get(endpoint)
        if not config:
            return True  # No rate limit configured
            
        current_time = time.time()
        # Clean up old timestamps
        self.rate_limits[endpoint] = [
            (ts, count) for ts, count in self.rate_limits[endpoint]
            if current_time - ts < config['period']
        ]
        
        # Count recent requests
        total_requests = sum(count for _, count in self.rate_limits[endpoint])
        
        if total_requests >= config['requests']:
            return False  # Rate limit exceeded
            
        # Add new request
        self.rate_limits[endpoint].append((current_time, 1))
        return True
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def _get(self, url: str, params: Optional[Dict] = None, endpoint: str = None) -> Dict:
        if endpoint and not await self._check_rate_limit(endpoint):
            raise Exception(f"Rate limit exceeded for {endpoint}. Please try again later.")
            
        try:
            session = await self._get_session()
            async with session.get(url, params=params, timeout=10.0) as response:  # Add timeout
                if response.status == 200:
                    return await response.json()
                raise Exception(f"API call failed: {response.status} for URL: {url}")
        except asyncio.TimeoutError:
            raise Exception("Request timed out. Please try again later.")
    
    # Weather API
    async def get_weather(self, city: str) -> Dict:
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": city,
            "appid": self.weather_key,
            "units": "metric",
            "lang": "kr"
        }
        return await self._get(url, params)
    
    # Steam API
    async def get_game_details(self, app_id: int) -> Optional[Dict]:
        """Get detailed game info including localized names"""
        # Check cache first
        if str(app_id) in self.korean_names_cache:
            return {'name': self.korean_names_cache[str(app_id)]}
        
        try:
            url = f"https://store.steampowered.com/api/appdetails"
            params = {
                "appids": app_id,
                "l": "koreana"
            }
            data = await self._get(url, params=params, endpoint='steam_details')
            
            if str(app_id) in data and data[str(app_id)]['success']:
                game_data = data[str(app_id)]['data']
                # Cache the Korean name
                self.korean_names_cache[str(app_id)] = game_data['name']
                self._save_korean_names_cache()
                return game_data
            return None
        except Exception as e:
            print(f"Error getting game details: {e}")
            return None

    async def _load_steam_games(self) -> List[Dict]:
        """Load Steam games from cache or API"""
        try:
            # Check if cache exists and is recent
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    last_updated = datetime.fromisoformat(cache_data['last_updated'])
                    
                    # If cache is still valid, use it
                    if datetime.now() - last_updated < self.cache_duration:
                        return cache_data['games']
            
            # If cache doesn't exist or is old, fetch from API
            print("Fetching full Steam games list...")
            
            # First try the v2 endpoint which should give all games at once
            url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
            try:
                data = await self._get(url, endpoint='steam_app_list')
                games = data['applist']['apps']
                print(f"Retrieved {len(games)} games from v2 API")
            except Exception as e:
                print(f"V2 API failed, falling back to v1: {e}")
                # Fall back to v1 with pagination if v2 fails
                games = []
                last_appid = 0
                
                while True:
                    url = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
                    params = {
                        "max_results": 50000,  # Maximum allowed
                        "last_appid": last_appid,
                        "include_games": True,
                        "include_dlc": False,
                        "include_software": False,
                        "include_videos": False,
                        "include_hardware": False
                    }
                    
                    try:
                        data = await self._get(url, params=params, endpoint='steam_app_list')
                        batch = data.get('response', {}).get('apps', [])
                        
                        if not batch:  # No more games
                            break
                            
                        games.extend(batch)
                        print(f"Retrieved {len(games)} games so far...")
                        
                        # Update last_appid for next page
                        last_appid = batch[-1]['appid']
                        
                        # Add delay to avoid rate limits
                        await asyncio.sleep(1)
                        
                    except Exception as e:
                        print(f"Error during pagination: {e}")
                        break
            
            print(f"Total games retrieved: {len(games)}")
            
            # Filter out non-game apps and format the data
            games = [
                {
                    'appid': app['appid'],
                    'name': app.get('name', ''),
                } for app in games
                if app.get('name')  # Only include apps with names
            ]
            
            # Save to cache
            cache_data = {
                'last_updated': datetime.now().isoformat(),
                'games': games
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            print(f"Cached {len(games)} games")
            return games
            
        except Exception as e:
            print(f"Error loading Steam games: {e}")
            # If loading from API fails, try to use cached data even if it's old
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    print(f"Using cached data with {len(cache_data['games'])} games")
                    return cache_data['games']
            raise
    
    async def find_game(self, game_name: str) -> Tuple[Optional[Dict], int, Optional[List[Dict]]]:
        try:
            # Sanitize input
            search_name = game_name.lower().strip()[:50]
            search_name = ''.join(c for c in search_name if c.isalnum() or c.isspace() or c >= '\u3131')
            
            # Load games from cache or API
            games = await self._load_steam_games()
            
            matches = []
            is_korean = any(char >= '\u3131' and char <= '\u9fff' for char in search_name)
            
            for app in games:
                app_name = app['name'].lower().strip()
                
                # Try to get Korean name for better matching
                if is_korean:
                    details = await self.get_game_details(app['appid'])
                    if details and 'name' in details:
                        korean_name = details.get('name', '').lower().strip()
                        if korean_name:
                            if search_name in korean_name:
                                app['korean_name'] = details['name']
                                matches.append((app, 95))
                                continue
                            
                            partial_ratio = fuzz.partial_ratio(korean_name, search_name)
                            if partial_ratio > 60:
                                app['korean_name'] = details['name']
                                matches.append((app, partial_ratio))
                                continue
                
                # Fall back to English name matching
                if app_name == search_name:
                    return app, 100, None
                
                if search_name in app_name:
                    matches.append((app, 95))
                    continue
                
                ratio = fuzz.token_sort_ratio(app_name, search_name)
                if ratio > 85:
                    matches.append((app, ratio))
            
            if not matches:
                return None, 0, None
            
            # Sort by similarity first
            matches.sort(key=lambda x: x[1], reverse=True)
            top_score = matches[0][1]
            
            # Get matches within 10% of top score
            similar_matches = [m[0] for m in matches if m[1] >= top_score - 10]
            
            # Limit number of matches to process
            matches = matches[:100]  # Only process top 100 matches
            
            # Limit similar matches
            similar_matches = similar_matches[:5]  # Only return top 5
            
            # If we have more than 3 similar matches, return the list
            if len(similar_matches) > 3:
                return None, 0, similar_matches[:5]  # Return top 5 matches
            
            # Otherwise, get player counts for top matches
            top_matches = []
            for match in matches[:3]:
                try:
                    player_count = await self.get_player_count(match[0]['appid'])
                    top_matches.append((match[0], match[1], player_count))
                except:
                    top_matches.append((match[0], match[1], 0))
            
            if not top_matches:
                return matches[0][0], matches[0][1], None
            
            # Sort by player count and similarity
            top_matches.sort(key=lambda x: (x[2], x[1]), reverse=True)
            return top_matches[0][0], top_matches[0][1], None
            
        except Exception as e:
            print(f"Steam API Error in find_game: {e}")
            raise
    
    async def get_player_count(self, app_id: int) -> int:
        try:
            url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={app_id}"
            data = await self._get(url, endpoint='steam_player_count')
            return data['response']['player_count']
        except Exception as e:
            print(f"Steam API Error in get_player_count: {e}")
            raise
    
    # Population API
    async def get_country_info(self, country_name: str) -> Dict:
        url = f"https://restcountries.com/v3.1/name/{country_name}"
        data = await self._get(url)
        return data[0]
    
    async def close(self):
        """Close the session when done"""
        try:
            if self.session:
                await self.session.close()
        except Exception as e:
            print(f"Error closing session: {e}")
        finally:
            self.session = None 
    
    def _load_korean_names_cache(self):
        """Load cached Korean names"""
        try:
            if os.path.exists(self.korean_names_file):
                with open(self.korean_names_file, 'r', encoding='utf-8') as f:
                    self.korean_names_cache = json.load(f)
        except Exception as e:
            print(f"Error loading Korean names cache: {e}")
            self.korean_names_cache = {}
    
    def _save_korean_names_cache(self):
        """Save Korean names to cache"""
        try:
            with open(self.korean_names_file, 'w', encoding='utf-8') as f:
                json.dump(self.korean_names_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving Korean names cache: {e}") 