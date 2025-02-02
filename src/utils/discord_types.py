from typing import TypeVar, Protocol, Union, Optional, Any, List, Dict, Tuple
from discord import Interaction, Message, Embed
from discord.ext.commands import Context

MessageableChannel = TypeVar('MessageableChannel', bound='Messageable')

class Messageable(Protocol):
    """Protocol for objects that can send messages"""
    async def send(
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        embeds: Optional[List[Embed]] = None,
        file: Optional[Any] = None,
        files: Optional[List[Any]] = None,
        delete_after: Optional[float] = None,
        reference: Optional[Message] = None,
        mention_author: Optional[bool] = None,
    ) -> Message: ...

class InteractionResponse(Protocol):
    """Protocol for interaction responses"""
    async def send_message(
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        embeds: Optional[List[Embed]] = None,
        ephemeral: bool = False,
    ) -> None: ...
    
    async def defer(
        self,
        *,
        ephemeral: bool = False,
        thinking: bool = True
    ) -> None: ...

    def is_done(self) -> bool: ...

class InteractionFollowup(Protocol):
    """Protocol for interaction followups"""
    async def send(
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        embeds: Optional[List[Embed]] = None,
        ephemeral: bool = False,
    ) -> Message: ... 