import functools
import logging

import discord

logger = logging.getLogger(__name__)


def command_handler():
    """Decorator for command handlers to handle common operations."""

    def decorator(func):
        """Wrap the command function with error handling."""
        @functools.wraps(func)
        async def wrapper(self, ctx_or_interaction, *args, **kwargs):
            """Handle common operations for commands

            Args:
                ctx_or_interaction: Command context or interaction
                args: Positional arguments for the command
                kwargs: Keyword arguments for the command
            """
            try:
                # Call the original function
                return await func(self, ctx_or_interaction, *args, **kwargs)

            except ValueError as e:
                # Handle user input errors
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(str(e), ephemeral=True)
                else:
                    await ctx_or_interaction.send(str(e))
                raise e  # Re-raise for logging

            except discord.Forbidden as e:
                # Handle permission errors
                message = str(e) or "권한이 없습니다"
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx_or_interaction.send(message)
                raise e  # Re-raise for logging

            except Exception as e:
                # Handle unexpected errors
                logger.error(f"Error in {func.__name__}: {e}")
                message = "예상치 못한 오류가 발생했습니다"
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx_or_interaction.send(message)
                raise e  # Re-raise for logging

        return wrapper

    return decorator
