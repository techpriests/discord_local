import asyncio
import logging
import sys

import discord
from api_service import APIService

from bot import DiscordBot
from commands import EntertainmentCommands, InformationCommands, SystemCommands
from config import Config

logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the bot"""
    try:
        # Load configuration
        try:
            config = Config()
            bot_token = config.BOT_TOKEN
            if not bot_token:
                raise ValueError("BOT_TOKEN environment variable is not set")
        except Exception as e:
            logger.error(f"Configuration error: {e}")
            raise ValueError("설정을 불러오는데 실패했습니다") from e

        # Initialize API service
        try:
            api_service = APIService(
                {"STEAM_API_KEY": config.STEAM_API_KEY, "WEATHER_API_KEY": config.WEATHER_API_KEY}
            )
            await api_service.initialize()
        except Exception as e:
            logger.error(f"API service initialization error: {e}")
            raise ValueError("API 서비스 초기화에 실패했습니다") from e

        # Initialize bot and load cogs
        try:
            bot = DiscordBot()
            cogs = [
                InformationCommands(api_service),
                EntertainmentCommands(),
                SystemCommands(bot.bot),
            ]
            await bot.load_cogs(cogs, api_service)
        except Exception as e:
            logger.error(f"Bot initialization error: {e}")
            raise ValueError("봇 초기화에 실패했습니다") from e

        # Start bot
        try:
            await bot.start(bot_token)
        except discord.LoginFailure as e:
            logger.error(f"Bot login failed: {e}")
            raise ValueError("봇 토큰이 잘못되었습니다") from e
        except Exception as e:
            logger.error(f"Bot startup error: {e}")
            raise ValueError("봇 시작에 실패했습니다") from e

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

    finally:
        # Cleanup
        try:
            if "api_service" in locals():
                await api_service.close()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


if __name__ == "__main__":
    try:
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")],
        )

        # Run bot
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
