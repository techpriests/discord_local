import discord
from discord.ext import commands
import asyncio
import logging

logger = logging.getLogger(__name__)

class MessageHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages that are commands to other bots"""
        # Ignore our own messages
        if message.author == self.bot.user:
            return

        # Check for the specific command pattern
        if message.content.startswith('샴 스팀 동접'):
            try:
                # Extract game name - everything after '샴 스팀 동접'
                game_name = message.content.replace('샴 스팀 동접', '', 1).strip()
                if not game_name:
                    return

                # Delete the original command message
                await message.delete()

                # Wait for the other bot's response
                def check(msg):
                    return (msg.author.name == "샴고양이" and 
                           msg.author.discriminator == "7251" and 
                           msg.channel == message.channel)

                try:
                    # Wait up to 5 seconds for the other bot's response
                    other_bot_msg = await self.bot.wait_for('message', check=check, timeout=5.0)
                    # Delete the other bot's response
                    await other_bot_msg.delete()
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for 샴고양이 bot response")

                # Use our own steam search
                ctx = await self.bot.get_context(message)
                steam_command = self.bot.get_command('스팀')
                if steam_command:
                    await ctx.invoke(steam_command, game_name=game_name)

            except Exception as e:
                logger.error(f"Error handling 샴고양이 bot command: {e}") 