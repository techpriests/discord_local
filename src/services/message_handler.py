import asyncio
import logging
import random

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class MessageHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.intercept_enabled = False  # Add flag to control interception

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle message events

        Args:
            message: Discord message object
        """
        try:
            # First handle normal message processing
            if not self._should_process_message(message):
                return

            await self._process_message(message)

            # Then handle bot interception if enabled
            await self._handle_bot_interception(message)

        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def _should_process_message(self, message: discord.Message) -> bool:
        """Check if message should be processed

        Args:
            message: Discord message object

        Returns:
            bool: True if message should be processed
        """
        # Ignore bot messages
        if message.author.bot:
            return False

        # Ignore DMs
        if not isinstance(message.channel, discord.TextChannel):
            return False

        # Ignore commands
        if message.content.startswith("!!"):
            return False

        return True

    async def _process_message(self, message: discord.Message):
        """Process a message

        Args:
            message: Discord message object
        """
        try:
            await self._handle_mentions(message)
            await self._handle_keywords(message)
            await self._handle_reactions(message)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def _handle_mentions(self, message: discord.Message):
        """Handle bot mentions in message

        Args:
            message: Discord message object
        """
        if self.bot.user in message.mentions:
            await self._send_mention_response(message)

    async def _send_mention_response(self, message: discord.Message):
        """Send response to bot mention

        Args:
            message: Discord message object
        """
        responses = [
            "네, 부르셨나요?",
            "안녕하세요!",
            "무엇을 도와드릴까요?",
            "명령어 목록은 !!help 를 입력해주세요!",
        ]
        await message.channel.send(random.choice(responses))

    async def _handle_keywords(self, message: discord.Message):
        """Handle keywords in message

        Args:
            message: Discord message object
        """
        content = message.content.lower()

        if "안녕" in content:
            await message.channel.send("안녕하세요!")
        elif "굿모닝" in content:
            await message.channel.send("좋은 아침이에요!")

    async def _handle_reactions(self, message: discord.Message):
        """Handle message reactions

        Args:
            message: Discord message object
        """
        content = message.content.lower()

        if "축하" in content:
            await message.add_reaction("🎉")
        elif "좋아" in content:
            await message.add_reaction("👍")

    async def _handle_bot_interception(self, message: discord.Message):
        """Handle bot command interception

        Args:
            message: Discord message object
        """
        try:
            # Skip if interception is disabled
            if not self.intercept_enabled:
                return

            # Ignore our own messages
            if message.author == self.bot.user:
                return

            # Check for the specific command pattern
            if message.content.startswith("샴 스팀 동접"):
                await self._handle_steam_intercept(message)

        except Exception as e:
            logger.error(f"Error in bot interception: {e}")

    async def _handle_steam_intercept(self, message: discord.Message):
        """Handle intercepted Steam player count command

        Args:
            message: Discord message object
        """
        try:
            # Extract game name
            game_name = message.content.replace("샴 스팀 동접", "", 1).strip()
            if not game_name:
                return

            # Delete the original command message
            await message.delete()

            # Wait for the other bot's response
            try:
                other_bot_msg = await self.bot.wait_for(
                    "message",
                    check=lambda msg: (
                        msg.author.name == "샴고양이"
                        and msg.author.discriminator == "7251"
                        and msg.channel == message.channel
                    ),
                    timeout=5.0,
                )
                await other_bot_msg.delete()
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for 샴고양이 bot response")

            # Use our own steam search
            ctx = await self.bot.get_context(message)
            steam_command = self.bot.get_command("스팀")
            if steam_command:
                await ctx.invoke(steam_command, game_name=game_name)

        except discord.Forbidden as e:
            logger.error(f"Permission error in message handling: {e}")
            await message.channel.send("메시지 삭제 권한이 없습니다")
        except Exception as e:
            logger.error(f"Error handling 샴고양이 bot command: {e}")
            await message.channel.send("명령어 처리 중 오류가 발생했습니다")
