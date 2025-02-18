from typing import TypeVar, Protocol, Dict, Any, Optional, List, Tuple, Union
from discord import Interaction, Embed, Message
from discord.ext.commands import Context

from src.utils.types import CommandContext
from src.utils.api_types import GameInfo, CountryInfo
from src.utils.discord_types import Messageable, InteractionResponse, InteractionFollowup

class APIServiceProtocol(Protocol):
    """Protocol for API service dependencies"""
    steam: Any  # Add missing attributes
    exchange: Any
    population: Any
    
    async def get_country_info(self, country_name: str) -> CountryInfo: ...
    async def find_game(self, name: str) -> Tuple[Optional[GameInfo], float, Optional[List[GameInfo]]]: ...
    async def get_exchange_rates(self) -> Dict[str, float]: ...

class CommandResponse(Protocol):
    """Protocol for command responses"""
    async def send_response(
        self,
        ctx_or_interaction: CommandContext,
        message: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        ephemeral: bool = False
    ) -> Optional[Message]: ...

CommandT = TypeVar('CommandT')
ResponseData = Dict[str, Any] 