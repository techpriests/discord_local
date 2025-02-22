import logging
import aiohttp
from typing import Dict, Any, Optional, List, Tuple, Union, cast
import asyncio
import json
from .base import BaseAPI
import urllib.parse
import math

logger = logging.getLogger(__name__)

class DNFAPI(BaseAPI[Dict[str, Any]]):
    """DNF API client for character information using Neople API"""
    
    BASE_URL = "https://api.neople.co.kr/df"
    
    # Server name mappings
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
        self._session = None

    async def initialize(self) -> None:
        """Initialize DNF API client"""
        self._initialized = True
        self._session = aiohttp.ClientSession()

    async def validate_credentials(self) -> bool:
        """Validate API credentials"""
        try:
            # Try to search for a character to validate API key
            result = await self.get_character_id("테스트", "cain")
            return result is not None
        except Exception:
            return False

    def _normalize_server_name(self, server_name: str) -> str:
        """Normalize server name to match API format"""
        server_name = server_name.lower()
        if server_name in self.SERVER_MAPPINGS.values():
            return server_name
        if server_name in [k.lower() for k in self.SERVER_MAPPINGS.keys()]:
            for k, v in self.SERVER_MAPPINGS.items():
                if k.lower() == server_name:
                    return v
        return "all"

    async def get_character_id(self, name: str, server: str) -> Optional[str]:
        """Get character ID from API"""
        try:
            encoded_name = urllib.parse.quote(name)
            url = f"{self.BASE_URL}/servers/{server}/characters"
            params = {
                "characterName": encoded_name,
                "apikey": self.neople_api_key
            }

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character ID: {response.status}")
                    return None

                data = await response.json()
                if data.get("rows") and len(data["rows"]) > 0:
                    return data["rows"][0]["characterId"]
                return None

        except Exception as e:
            logger.error(f"Error getting character ID: {e}")
            return None

    async def get_character_basic(self, server: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Get character basic information"""
        try:
            url = f"{self.BASE_URL}/servers/{server}/characters/{character_id}"
            params = {"apikey": self.neople_api_key}

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character basic info: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting character basic info: {e}")
            return None

    async def get_character_status(self, server: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Get character status (stats) information"""
        try:
            url = f"{self.BASE_URL}/servers/{server}/characters/{character_id}/status"
            params = {"apikey": self.neople_api_key}

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character status: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting character status: {e}")
            return None

    async def get_character_equipment(self, server: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Get character equipment information"""
        try:
            url = f"{self.BASE_URL}/servers/{server}/characters/{character_id}/equipment"
            params = {"apikey": self.neople_api_key}

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character equipment: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting character equipment: {e}")
            return None

    async def get_character_avatar(self, server: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Get character avatar information"""
        try:
            url = f"{self.BASE_URL}/servers/{server}/characters/{character_id}/avatar"
            params = {"apikey": self.neople_api_key}

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character avatar: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting character avatar: {e}")
            return None

    async def get_character_creature(self, server: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Get character creature information"""
        try:
            url = f"{self.BASE_URL}/servers/{server}/characters/{character_id}/creature"
            params = {"apikey": self.neople_api_key}

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get character creature: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting character creature: {e}")
            return None

    async def get_skill_info(self, job_id: str, job_grow_id: str) -> Optional[Dict[str, Any]]:
        """Get character skill information"""
        try:
            url = f"{self.BASE_URL}/skills/{job_id}"
            params = {
                "jobGrowId": job_grow_id,
                "apikey": self.neople_api_key
            }

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get skill info: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting skill info: {e}")
            return None

    async def get_item_info(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Get item detailed information"""
        try:
            url = f"{self.BASE_URL}/items/{item_id}"
            params = {"apikey": self.neople_api_key}

            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Failed to get item info: {response.status}")
                    return None
                return await response.json()

        except Exception as e:
            logger.error(f"Error getting item info: {e}")
            return None

    def _calculate_base_stats(self, status: Dict[str, Any]) -> Dict[str, float]:
        """Calculate base stats from character status
        
        Args:
            status: Character status data from API
            
        Returns:
            Dict containing calculated base stats
        """
        try:
            stats = status.get("status", {})
            
            # Get base stats
            base_str = float(stats.get("str", 0))
            base_int = float(stats.get("int", 0))
            base_vit = float(stats.get("vit", 0))
            base_spr = float(stats.get("spr", 0))
            
            # Get additional stats
            physical_attack = float(stats.get("physicalAttack", 0))
            magical_attack = float(stats.get("magicalAttack", 0))
            independent_attack = float(stats.get("independentAttack", 0))
            physical_crit = float(stats.get("physicalCritical", 0))
            magical_crit = float(stats.get("magicalCritical", 0))
            
            return {
                "base_str": base_str,
                "base_int": base_int,
                "base_vit": base_vit,
                "base_spr": base_spr,
                "physical_attack": physical_attack,
                "magical_attack": magical_attack,
                "independent_attack": independent_attack,
                "physical_crit": physical_crit,
                "magical_crit": magical_crit
            }
        except Exception as e:
            logger.error(f"Error calculating base stats: {e}")
            return {}

    def _calculate_equipment_modifiers(self, equipment: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate stat modifiers from equipment
        
        Args:
            equipment: List of equipment data from API
            
        Returns:
            Dict containing equipment modifiers
        """
        try:
            modifiers = {
                "str_mod": 0,
                "int_mod": 0,
                "vit_mod": 0,
                "spr_mod": 0,
                "physical_attack_mod": 0,
                "magical_attack_mod": 0,
                "independent_attack_mod": 0,
                "physical_crit_mod": 0,
                "magical_crit_mod": 0,
                "elemental_damage": 0,
                "skill_attack_percent": 0,
                "additional_damage": 0
            }

            for item in equipment:
                # Get reinforcement level
                reinforce = int(item.get("reinforce", 0))
                
                # Get amplification level
                amplify = int(item.get("amplificationName", "0").replace("+", ""))
                
                # Get item stats
                for option in item.get("options", []):
                    value = float(option.get("value", 0))
                    match option.get("type", ""):
                        case "str": modifiers["str_mod"] += value
                        case "int": modifiers["int_mod"] += value
                        case "vit": modifiers["vit_mod"] += value
                        case "spr": modifiers["spr_mod"] += value
                        case "physical_attack": modifiers["physical_attack_mod"] += value
                        case "magical_attack": modifiers["magical_attack_mod"] += value
                        case "independent_attack": modifiers["independent_attack_mod"] += value
                        case "physical_critical": modifiers["physical_crit_mod"] += value
                        case "magical_critical": modifiers["magical_crit_mod"] += value
                        case "element_fire" | "element_water" | "element_light" | "element_dark":
                            modifiers["elemental_damage"] += value
                        case "skill_attack": modifiers["skill_attack_percent"] += value
                        case "additional_damage": modifiers["additional_damage"] += value

                # Add reinforcement/amplification bonuses
                if reinforce > 0:
                    modifiers["physical_attack_mod"] += reinforce * 10
                    modifiers["magical_attack_mod"] += reinforce * 10
                
                if amplify > 0:
                    modifiers["physical_attack_mod"] += amplify * 15
                    modifiers["magical_attack_mod"] += amplify * 15
                    modifiers["independent_attack_mod"] += amplify * 15

            return modifiers

        except Exception as e:
            logger.error(f"Error calculating equipment modifiers: {e}")
            return {}

    def _calculate_skill_modifiers(self, skills: List[Dict[str, Any]], buff_power: Dict[str, Any]) -> Dict[str, float]:
        """Calculate modifiers from skills and buffs
        
        Args:
            skills: List of skill data from API
            buff_power: Buff power data from API
            
        Returns:
            Dict containing skill modifiers
        """
        try:
            modifiers = {
                "skill_attack_percent": 0,
                "additional_damage": 0,
                "buff_strength": float(buff_power.get("skillLevelDetail", {}).get("buff", 0))
            }

            # Add passive skill bonuses
            for skill in skills:
                if skill.get("type", "") == "passive":
                    for option in skill.get("options", []):
                        value = float(option.get("value", 0))
                        match option.get("type", ""):
                            case "skill_attack": modifiers["skill_attack_percent"] += value
                            case "additional_damage": modifiers["additional_damage"] += value

            return modifiers

        except Exception as e:
            logger.error(f"Error calculating skill modifiers: {e}")
            return {}

    def calculate_damage(
        self, 
        status: Dict[str, Any], 
        equipment: List[Dict[str, Any]], 
        skills: List[Dict[str, Any]], 
        buff_power: Dict[str, Any]
    ) -> Dict[str, Union[float, str]]:
        """Calculate character's damage output
        
        Args:
            status: Character status data
            equipment: Equipment data
            skills: Skill data
            buff_power: Buff power data
            
        Returns:
            Dict containing calculated damage values
        """
        try:
            # Get base stats
            base_stats = self._calculate_base_stats(status)
            if not base_stats:
                return {"error": "Failed to calculate base stats"}

            # Get equipment modifiers
            equip_mods = self._calculate_equipment_modifiers(equipment)
            if not equip_mods:
                return {"error": "Failed to calculate equipment modifiers"}

            # Get skill modifiers
            skill_mods = self._calculate_skill_modifiers(skills, buff_power)
            if not skill_mods:
                return {"error": "Failed to calculate skill modifiers"}

            # Calculate final stats
            final_str = base_stats["base_str"] + equip_mods["str_mod"]
            final_int = base_stats["base_int"] + equip_mods["int_mod"]
            
            # Calculate attack power
            physical_attack = (
                base_stats["physical_attack"] + 
                equip_mods["physical_attack_mod"] + 
                (final_str * 2)
            )
            
            magical_attack = (
                base_stats["magical_attack"] + 
                equip_mods["magical_attack_mod"] + 
                (final_int * 2)
            )
            
            independent_attack = (
                base_stats["independent_attack"] + 
                equip_mods["independent_attack_mod"]
            )

            # Calculate critical rates
            physical_crit = min(97, base_stats["physical_crit"] + equip_mods["physical_crit_mod"])
            magical_crit = min(97, base_stats["magical_crit"] + equip_mods["magical_crit_mod"])

            # Calculate damage multipliers
            skill_attack = 1 + ((equip_mods["skill_attack_percent"] + skill_mods["skill_attack_percent"]) / 100)
            additional_damage = 1 + ((equip_mods["additional_damage"] + skill_mods["additional_damage"]) / 100)
            elemental_damage = 1 + (equip_mods["elemental_damage"] / 100)
            crit_damage = 1.5  # Base crit damage multiplier

            # Calculate average damage per attack
            physical_dpa = (
                physical_attack * 
                skill_attack * 
                additional_damage * 
                elemental_damage * 
                (1 + (physical_crit/100 * (crit_damage - 1)))
            )

            magical_dpa = (
                magical_attack * 
                skill_attack * 
                additional_damage * 
                elemental_damage * 
                (1 + (magical_crit/100 * (crit_damage - 1)))
            )

            independent_dpa = (
                independent_attack * 
                skill_attack * 
                additional_damage * 
                elemental_damage
            )

            # Return calculated values
            return {
                "physical_attack": physical_attack,
                "magical_attack": magical_attack,
                "independent_attack": independent_attack,
                "physical_crit": physical_crit,
                "magical_crit": magical_crit,
                "skill_attack": skill_attack,
                "additional_damage": additional_damage,
                "elemental_damage": elemental_damage,
                "physical_dpa": physical_dpa,
                "magical_dpa": magical_dpa,
                "independent_dpa": independent_dpa,
                "buff_strength": skill_mods["buff_strength"]
            }

        except Exception as e:
            logger.error(f"Error calculating damage: {e}")
            return {"error": f"Failed to calculate damage: {str(e)}"}

    async def search_character(self, name: str, server: str = "all") -> Optional[Dict[str, Any]]:
        """Search for a character by name and server
        
        Args:
            name: Character name to search for
            server: Server name (defaults to all servers)
            
        Returns:
            Optional[Dict[str, Any]]: Character information if found
            
        Raises:
            ValueError: If the feature is currently disabled
        """
        raise ValueError("던전앤파이터 캐릭터 검색 기능이 현재 비활성화되어 있습니다. 추후 업데이트 예정입니다.")

    async def close(self) -> None:
        """Cleanup resources"""
        if self._session:
            await self._session.close()
        await super().close() 