import logging
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, List, Tuple
import asyncio
import json
import re
from .base import BaseAPI
import urllib.parse

logger = logging.getLogger(__name__)

class DundamAPI(BaseAPI[Dict[str, Any]]):
    """Dundam API client for character information from dundam.xyz"""
    
    BASE_URL = "https://dundam.xyz"
    SEARCH_URL = f"{BASE_URL}/search"
    CHARACTER_URL = f"{BASE_URL}/character"
    NEOPLE_BASE_URL = "https://api.neople.co.kr/df"
    
    # Server name mappings (add more if needed)
    SERVER_MAPPINGS = {
        "카인": "cain",
        "디레지에": "diregie",
        "시로코": "siroco",
        "프레이": "prey",
        "카시야스": "casillas",
        "힐더": "hilder",
        "안톤": "anton",
        "바칼": "bakal"
    }
    
    def __init__(self, neople_api_key: str):
        super().__init__()
        self.neople_api_key = neople_api_key

    async def initialize(self) -> None:
        """Initialize Dundam API client"""
        self._initialized = True
        self._session = None

    async def validate_credentials(self) -> bool:
        """Validate credentials - not needed for web scraping"""
        return True

    def _normalize_server_name(self, server_name: str) -> str:
        """Normalize server name to match dundam.xyz format"""
        server_name = server_name.lower()
        # If it's already an English name, return as is
        if server_name in self.SERVER_MAPPINGS.values():
            return server_name
        # If it's a Korean name, convert to English
        if server_name in [k.lower() for k in self.SERVER_MAPPINGS.keys()]:
            for k, v in self.SERVER_MAPPINGS.items():
                if k.lower() == server_name:
                    return v
        # If "all" or unknown, return "all"
        return "all"

    async def get_character_id(self, name: str, server: str) -> Optional[str]:
        """Get character ID from Neople API
        
        Args:
            name: Character name to search for
            server: Server name in English format
            
        Returns:
            Optional[str]: Character ID if found
        """
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()

            # URL encode the character name
            encoded_name = urllib.parse.quote(name)
            url = f"{self.NEOPLE_BASE_URL}/servers/{server}/characters"
            
            params = {
                "characterName": encoded_name,
                "apikey": self.neople_api_key
            }

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character ID for {name} on {server}: {response.status}")
                    response_text = await response.text()
                    logger.error(f"Response: {response_text}")
                    return None

                data = await response.json()
                logger.info(f"Neople API response for {name}: {data}")
                
                if data.get("rows") and len(data["rows"]) > 0:
                    return data["rows"][0]["characterId"]
                return None

        except Exception as e:
            logger.error(f"Error getting character ID for {name} on {server}: {e}")
            return None

    async def get_character_details(self, server: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Get character details from dundam.xyz using character ID
        
        Args:
            server: Server name in English format
            character_id: Character ID from Neople API
            
        Returns:
            Optional[Dict[str, Any]]: Character details if found
        """
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()

            url = f"{self.CHARACTER_URL}"
            params = {
                "server": server,
                "key": character_id
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": "https://dundam.xyz/"
            }

            async with self._session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character details for ID {character_id}: {response.status}")
                    response_text = await response.text()
                    logger.error(f"Response: {response_text}")
                    return None

                html = await response.text()
                logger.debug(f"Dundam.xyz response HTML: {html[:500]}...")  # Log first 500 chars
                
                soup = BeautifulSoup(html, "html.parser")
                
                # Parse the character details from the response
                scripts = soup.find_all("script", {"type": "text/javascript"})
                for script in scripts:
                    if script.string and "window.__INITIAL_STATE__" in script.string:
                        try:
                            data_str = script.string.split("window.__INITIAL_STATE__ = ")[1].split(";</script>")[0]
                            data = json.loads(data_str)
                            logger.info(f"Parsed Dundam.xyz data: {json.dumps(data, ensure_ascii=False)}")
                            
                            if "character" in data:
                                char = data["character"]
                                return {
                                    "name": char.get("name", ""),
                                    "server": server,
                                    "level": str(char.get("level", "")),
                                    "total_damage": self._parse_damage_text(str(char.get("totalDamage", "0"))),
                                    "character_id": character_id,
                                    "job_name": char.get("jobName", ""),  # Added job name
                                    "job_growth_name": char.get("jobGrowName", "")  # Added job growth name
                                }
                        except Exception as e:
                            logger.error(f"Error parsing script data: {e}")
                            logger.error(f"Problematic script content: {script.string[:200]}...")  # Log first 200 chars

                return None

        except Exception as e:
            logger.error(f"Error getting character details for ID {character_id}: {e}")
            return None

    async def search_character(self, name: str, server: str = "all") -> Optional[Dict[str, Any]]:
        """Search for a character by name and server
        
        Args:
            name: Character name to search for
            server: Server name (defaults to all servers)
            
        Returns:
            Optional[Dict[str, Any]]: Character information if found
        """
        try:
            server = self._normalize_server_name(server)
            
            # First get the character ID from Neople API
            character_id = await self.get_character_id(name, server)
            if not character_id:
                return None

            # Then get the character details from dundam.xyz
            return await self.get_character_details(server, character_id)

        except Exception as e:
            logger.error(f"Error searching character {name} on {server}: {e}")
            return None

    def _parse_damage_text(self, damage_text: str) -> str:
        """Parse damage text into a formatted string
        
        Args:
            damage_text: Raw damage text from the website
            
        Returns:
            str: Formatted damage string
        """
        try:
            # Remove all non-numeric characters except decimal points
            numbers = re.findall(r'[\d.]+', damage_text)
            if not numbers:
                return "0"
                
            # Convert to proper format (e.g., "52억 4450만")
            value = float("".join(numbers))
            
            if value >= 100000000:  # 1억 이상
                billions = value // 100000000
                millions = (value % 100000000) // 10000
                if millions > 0:
                    return f"{int(billions)}억 {int(millions):04d}만"
                return f"{int(billions)}억"
            elif value >= 10000:  # 1만 이상
                millions = value // 10000
                return f"{int(millions)}만"
            else:
                return str(int(value))
                
        except Exception as e:
            logger.error(f"Error parsing damage text '{damage_text}': {e}")
            return "알 수 없음"

    async def close(self) -> None:
        """Cleanup resources"""
        if self._session:
            await self._session.close()
        await super().close() 