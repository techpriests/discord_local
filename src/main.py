import asyncio
import logging
import sys
from typing import NoReturn

import discord
from api_service import APIService

from src.bot import DiscordBot
from commands import EntertainmentCommands, InformationCommands, SystemCommands
from src.config import Config

logger = logging.getLogger(__name__)

def setup_logging() -> None:
    """Configure logging settings"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("bot.log", encoding="utf-8")
        ]
    )

async def start_bot(config: Config) -> NoReturn:
    """Start the Discord bot
    
    Args:
        config: Application configuration

    Raises:
        SystemExit: If bot fails to start
    """
    try:
        bot = DiscordBot(config)
        async with bot:
            await bot.start(config.discord_token)
    except discord.LoginFailure as e:
        logger.error(f"Failed to login: {e}")
        raise SystemExit("Discord 로그인에 실패했습니다") from e
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise SystemExit("봇 실행 중 오류가 발생했습니다") from e

async def main() -> NoReturn:
    """Main entry point
    
    Raises:
        SystemExit: If initialization fails or bot crashes
    """
    try:
        # Load configuration
        try:
            config = Config()
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise SystemExit("설정을 불러오는데 실패했습니다") from e

        # Start bot
        await start_bot(config)

    except SystemExit as e:
        logger.error(f"Bot terminated: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Set up logging
    setup_logging()
    
    # Run bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
