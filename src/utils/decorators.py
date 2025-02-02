"""Utility decorators for command handling"""

import functools
import logging
from typing import Any, Callable, TypeVar, Union, cast

import discord
from discord.ext import commands

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
            self,
            ctx_or_interaction: Union[commands.Context, discord.Interaction],
            *args: Any,
            **kwargs: Any
        ) -> Any:
            try:
                return await func(self, ctx_or_interaction, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                if isinstance(ctx_or_interaction, discord.Interaction):
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(
                            "명령어 처리 중 오류가 발생했습니다", ephemeral=True
                        )
                    else:
                        await ctx_or_interaction.response.send_message(
                            "명령어 처리 중 오류가 발생했습니다", ephemeral=True
                        )
                else:
                    await ctx_or_interaction.send("명령어 처리 중 오류가 발생했습니다")
                raise
        return cast(CommandFunc, wrapper)
    return decorator
