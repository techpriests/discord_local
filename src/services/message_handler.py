import asyncio
import logging
import random
from typing import Optional, Dict, Any, Protocol, Union, List, cast

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class MessageHandler(commands.Cog):
    """Handler for message-related events"""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize message handler
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.intercept_enabled = False
        self._last_message: Optional[str] = None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle message events
        
        Args:
            message: Discord message object
        """
        try:
            if message.author.bot:
                return

            await self._handle_bot_interception(message)
            await self._handle_command(message)

        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def _should_process_message(self, message: discord.Message) -> bool:
        """Check if message should be processed

        Args:
            message: Discord message object

        Returns:
            bool: True if message should be processed
        """
        # Ignore DMs
        if not isinstance(message.channel, discord.TextChannel):
            return False

        # Ignore commands
        if message.content.startswith("!!"):
            return False

        return True

    async def _handle_bot_interception(self, message: discord.Message) -> None:
        """Handle bot command interception
        
        Args:
            message: Discord message object
        """
        try:
            if not self.intercept_enabled:
                return
            if message.author == self.bot.user:
                return

            if message.content.startswith("샴 스팀 동접"):
                await self._handle_steam_intercept(message)

        except Exception as e:
            logger.error(f"Error in bot interception: {e}")

    async def _handle_steam_intercept(self, message: discord.Message) -> None:
        """Handle Steam command interception
        
        Args:
            message: Discord message object
        """
        try:
            await message.add_reaction("👍")
            ctx = await self.bot.get_context(message)
            steam_command = self.bot.get_command("스팀")
            if steam_command:
                await ctx.invoke(steam_command)
        except Exception as e:
            logger.error(f"Error handling Steam intercept: {e}")

    async def _handle_command(self, message: discord.Message) -> None:
        """Handle command messages
        
        Args:
            message: Discord message object
        """
        try:
            response = await self.process_command(message.content)
            if response:
                await message.channel.send(response)
        except Exception as e:
            logger.error(f"Error handling command: {e}")

    async def process_command(self, command: str) -> Optional[str]:
        """Process command message
        
        Args:
            command: Command to process

        Returns:
            Optional[str]: Command response if any
        """
        try:
            if command.lower() == "help":
                return "사용 가능한 명령어: muhelp, 안녕"
            return None
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            return None

    async def _handle_mentions(self, message: discord.Message) -> None:
        """Handle bot mentions in message

        Args:
            message: Discord message object
        """
        if self.bot.user in message.mentions:
            await self._send_mention_response(message)

    async def _send_mention_response(self, message: discord.Message) -> None:
        """Send response to bot mention

        Args:
            message: Discord message object
        """
        responses = [
            "불럿어?",
            "반가워.",
            "왜 그래?",
        ]
        await message.channel.send(random.choice(responses))

    async def _handle_keywords(self, message: discord.Message) -> None:
        """Handle keywords in message

        Args:
            message: Discord message object
        """
        content = message.content.lower()
        if "안녕" in content:
            await message.channel.send("안녕!")
        elif "굿모닝" in content:
            await message.channel.send("좋은 아침이야!")

    async def _handle_reactions(self, message: discord.Message) -> None:
        """Handle message reactions

        Args:
            message: Discord message object
        """
        content = message.content.lower()
        if "축하" in content:
            await message.add_reaction("🎉")
        elif "좋아" in content:
            await message.add_reaction("👍")

    async def handle_message(self, message: str) -> Optional[str]:
        """Handle incoming message
        
        Args:
            message: Message to handle

        Returns:
            Optional[str]: Response message if any
        """
        try:
            # Basic message handling logic
            if message.lower().startswith("안녕"):
                return "안녕!"
            return None
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return None
