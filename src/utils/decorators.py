import functools
from discord.ext import commands
import discord
import logging

logger = logging.getLogger(__name__)

def command_handler():
    """Decorator for command handlers to handle common operations"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, ctx_or_interaction, *args, **kwargs):
            processing_msg = None
            try:
                # Get user name
                user_name = (ctx_or_interaction.user.display_name 
                           if isinstance(ctx_or_interaction, discord.Interaction) 
                           else ctx_or_interaction.author.display_name)
                
                # Show processing message
                processing_text = f"{user_name}님의 명령어를 처리중입니다..."
                
                if isinstance(ctx_or_interaction, discord.Interaction):
                    if not ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.response.defer()
                        await ctx_or_interaction.followup.send(processing_text, ephemeral=True)
                else:
                    processing_msg = await ctx_or_interaction.send(processing_text)

                # Execute command
                result = await func(self, ctx_or_interaction, *args, **kwargs)

                # Clean up processing message
                if processing_msg:
                    await processing_msg.delete()

                return result

            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                error_msg = str(e)
                if isinstance(ctx_or_interaction, discord.Interaction):
                    if not ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.response.send_message(error_msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(error_msg)
                    if processing_msg:
                        await processing_msg.delete()

        return wrapper
    return decorator 