"""Utility decorators for command handling"""

import functools
import logging
from typing import Any, Callable, TypeVar, cast

import discord
from discord.ext import commands
from src.utils.types import CommandContext

logger = logging.getLogger(__name__)

T = TypeVar('T')
CommandFunc = Callable[..., Any]

def command_handler() -> Callable[[CommandFunc], CommandFunc]:
    """Decorator for handling both slash and prefix commands
    
    Returns:
        Callable: Decorated command handler
    """
    def decorator(func: CommandFunc) -> CommandFunc:
        @functools.wraps(func)
        async def wrapper(
            self: Any,
            ctx_or_interaction: CommandContext,
            *args: Any,
            **kwargs: Any
        ) -> Any:
            try:
                return await func(self, ctx_or_interaction, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                await self.send_response(
                    ctx_or_interaction,
                    "명령어 처리 중 오류가 발생했습니다",
                    ephemeral=True
                )
                raise
        return cast(CommandFunc, wrapper)
    return decorator
