import asyncio
import logging
import sys
import os
from typing import NoReturn, Dict
from datetime import datetime, timedelta

import discord
from src.services.api.service import APIService

from src.bot import DiscordBot
from src.commands import EntertainmentCommands, InformationCommands, SystemCommands

logger = logging.getLogger(__name__)

# Add constants for retry logic
MAX_RETRY_ATTEMPTS = 3  # Maximum number of restart attempts
BASE_RETRY_DELAY = 5  # Base delay in seconds
MAX_RETRY_DELAY = 300  # Maximum delay (5 minutes)

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

def get_config() -> Dict[str, str]:
    """Get configuration from environment variables"""
    return {
        "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", ""),
        "STEAM_API_KEY": os.getenv("STEAM_API_KEY", ""),
        "CL_API_KEY": os.getenv("CL_API_KEY", ""),
    }

async def start_bot(config: Dict[str, str], attempt: int = 1) -> NoReturn:
    """Start the Discord bot with retry logic
    
    Args:
        config: Application configuration
        attempt: Current attempt number

    Raises:
        SystemExit: If bot fails to start after maximum retries
    """
    try:
        logger.info("Creating bot instance...")
        bot = DiscordBot(config)
        logger.info("Bot instance created successfully")
        
        logger.info("Starting bot with token...")
        async with bot:
            logger.info("Entering bot context manager")
            try:
                await bot.start(config["DISCORD_TOKEN"])
            except Exception as e:
                logger.error(f"Error during bot.start(): {e}", exc_info=True)
                raise
    except discord.LoginFailure as e:
        logger.error(f"Failed to login: {e}", exc_info=True)
        raise SystemExit("Discord 로그인에 실패했습니다") from e
    except Exception as e:
        if attempt >= MAX_RETRY_ATTEMPTS:
            logger.error(
                f"Bot failed to start after {MAX_RETRY_ATTEMPTS} attempts. "
                f"Last error: {e}",
                exc_info=True
            )
            raise SystemExit(
                f"봇이 {MAX_RETRY_ATTEMPTS}회 시도 후에도 시작하지 못했습니다.\n"
                f"마지막 오류: {str(e)}"
            ) from e
        
        # Calculate delay with exponential backoff
        delay = min(BASE_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
        logger.warning(
            f"Bot crashed (attempt {attempt}/{MAX_RETRY_ATTEMPTS}). "
            f"Retrying in {delay} seconds..."
        )
        
        await asyncio.sleep(delay)
        await start_bot(config, attempt + 1)

async def main() -> NoReturn:
    """Main entry point
    
    Raises:
        SystemExit: If initialization fails or bot crashes
    """
    try:
        # Load configuration from environment
        logger.info("Loading configuration from environment...")
        config = get_config()
        
        # Validate config
        if not all(config.values()):
            missing_vars = [k for k, v in config.items() if not v]
            error_msg = (
                f"Missing required environment variables: {', '.join(missing_vars)}\n"
                "Please ensure all required environment variables are set."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        logger.info("Starting bot with retry logic...")
        await start_bot(config)

    except SystemExit as e:
        logger.error(f"Bot terminated: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    # Set up logging
    setup_logging()
    logger.info("Starting bot application...")
    
    # Run bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
