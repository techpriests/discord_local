import asyncio
import logging
import sys
import os
from typing import NoReturn, Dict

import discord
from src.services.api.service import APIService

from src.bot import DiscordBot
from src.commands import EntertainmentCommands, InformationCommands, SystemCommands

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

def get_config() -> Dict[str, str]:
    """Get configuration from environment variables"""
    return {
        "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", ""),
        "STEAM_API_KEY": os.getenv("STEAM_API_KEY", ""),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
    }

async def start_bot(config: Dict[str, str]) -> NoReturn:
    """Start the Discord bot
    
    Args:
        config: Application configuration

    Raises:
        SystemExit: If bot fails to start
    """
    try:
        bot = DiscordBot(config)
        async with bot:
            await bot.start(config["DISCORD_TOKEN"])
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
        # Load configuration from environment
        config = get_config()
        
        # Validate config
        if not all(config.values()):
            raise ValueError("Missing required environment variables")
            
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
