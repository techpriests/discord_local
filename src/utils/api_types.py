from typing import TypedDict, List, Dict, Any, Optional

class GameInfo(TypedDict):
    name: str
    player_count: int
    peak_24h: int
    peak_7d: int
    avg_7d: float

class CountryInfo(TypedDict):
    name: Dict[str, str]
    population: int
    capital: List[str]
    region: str
    flags: Dict[str, str]

class WeatherInfo(TypedDict):
    main: Dict[str, float]
    weather: List[Dict[str, Any]]
    name: str

class ExchangeRates(TypedDict):
    rates: Dict[str, float]
    base: str
    timestamp: int 