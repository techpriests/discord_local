from typing import TypedDict, List, Dict, Any, Optional, Tuple

class GameInfo(TypedDict):
    """Steam game information"""
    name: str  # Game name (Korean name if available, otherwise English name)
    player_count: int  # Current player count
    image_url: Optional[str]  # Game image URL
    app_id: Optional[int]  # Steam app ID for store link

class CountryInfo(TypedDict):
    name: Dict[str, str]
    population: int
    capital: List[str]
    region: str
    flags: Dict[str, str]

class ExchangeRates(TypedDict):
    rates: Dict[str, float]
    base: str
    timestamp: int 