import aiohttp
from typing import Dict, Optional, Tuple, List
from fuzzywuzzy import fuzz

class APIService:
    def __init__(self, weather_key: str, steam_key: str):
        self.weather_key = weather_key
        self.steam_key = steam_key
    
    async def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                raise Exception(f"API call failed: {response.status}")
    
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
    async def find_game(self, game_name: str) -> Tuple[Optional[Dict], int]:
        url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
        data = await self._get(url)
        
        matches = []
        for app in data['applist']['apps']:
            ratio = fuzz.ratio(app['name'].lower(), game_name.lower())
            if ratio > 80:
                matches.append((app, ratio))
        
        if not matches:
            return None, 0
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0][0], matches[0][1]
    
    async def get_player_count(self, app_id: int) -> int:
        url = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
        params = {"appid": app_id}
        data = await self._get(url, params)
        return data['response']['player_count']
    
    # Population API
    async def get_country_info(self, country_name: str) -> Dict:
        url = f"https://restcountries.com/v3.1/name/{country_name}"
        data = await self._get(url)
        return data[0] 