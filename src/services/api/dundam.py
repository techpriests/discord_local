import logging
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, List, Tuple
import asyncio
import json
import re
from .base import BaseAPI

logger = logging.getLogger(__name__)

class DundamAPI(BaseAPI[Dict[str, Any]]):
    """Dundam API client for character information from dundam.xyz"""
    
    BASE_URL = "https://dundam.xyz"
    SEARCH_URL = f"{BASE_URL}/search"
    CHARACTER_URL = f"{BASE_URL}/character"
    
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
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": "https://dundam.xyz/"
            }

            # Create session if not exists
            if not self._session:
                self._session = aiohttp.ClientSession()

            # First try the search endpoint
            async with self._session.get(
                self.SEARCH_URL,
                params={"server": server, "name": name},
                headers=headers
            ) as response:
                if response.status != 200:
                    logger.error(f"Failed to search character {name} on {server}: {response.status}")
                    return None

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                # Try to find character info
                character_info = {}
                
                # Look for character data in script tags
                scripts = soup.find_all("script", {"type": "text/javascript"})
                for script in scripts:
                    if script.string and "window.__INITIAL_STATE__" in script.string:
                        try:
                            # Extract JSON data
                            data_str = script.string.split("window.__INITIAL_STATE__ = ")[1].split(";</script>")[0]
                            data = json.loads(data_str)
                            
                            # Look for character data in the state
                            if "characters" in data:
                                for char in data["characters"]:
                                    if char["name"].lower() == name.lower():
                                        return {
                                            "name": char["name"],
                                            "server": char.get("server", server),
                                            "level": str(char.get("level", "")),
                                            "total_damage": self._parse_damage_text(str(char.get("totalDamage", "0")))
                                        }
                        except Exception as e:
                            logger.error(f"Error parsing script data: {e}")

                # If we couldn't find in scripts, try direct HTML parsing
                character_div = soup.find("div", {"data-character-name": name})
                if character_div:
                    character_info["name"] = name
                    character_info["server"] = character_div.get("data-server", server)
                    character_info["level"] = character_div.get("data-level", "")
                    
                    damage_div = character_div.find("div", {"class": "damage"})
                    if damage_div:
                        damage_text = damage_div.get_text(strip=True)
                        character_info["total_damage"] = self._parse_damage_text(damage_text)
                    
                    return character_info

            return None

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