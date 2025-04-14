import asyncio
import logging
import sys
import os
from typing import NoReturn, Dict, Optional
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from src.services.api.service import APIService

from src.bot import DiscordBot
from src.commands import EntertainmentCommands, InformationCommands, SystemCommands, AICommands

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
            logging.FileHandler("bot.log", encoding="utf-8", mode="a")
        ]
    )

def get_config() -> Dict[str, str]:
    """Get configuration from environment variables"""
    return {
        "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", ""),
        "STEAM_API_KEY": os.getenv("STEAM_API_KEY", ""),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
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

class MuelsyseBot(commands.Bot):
    """Main bot class for Muelsyse"""

    def __init__(self, command_prefix, intents, activity, status=discord.Status.online) -> None:
        """Initialize the bot

        Args:
            command_prefix: Command prefix (list or string)
            intents: Discord intents for permissions
            activity: Discord presence activity
            status: Discord presence status
        """
        super().__init__(
            command_prefix=command_prefix,
            intents=intents,
            activity=activity,
            status=status
        )
        
        # Initialize services
        self.api_service: Optional[APIService] = None
        
        # Track initialization status
        self.initialized = False
        
        # Add command groups
        self.ai_commands = AICommands()
        self.entertainment_commands = EntertainmentCommands()
        self.information_commands = InformationCommands()
        self.system_commands = SystemCommands()
        
        # Add cogs (command categories)
        logger.info("Adding command cogs...")
        self.add_cog(self.ai_commands)
        self.add_cog(self.entertainment_commands)
        self.add_cog(self.information_commands)
        self.add_cog(self.system_commands)
        
    async def setup_hook(self) -> None:
        """Setup hook that's called before the bot starts"""
        logger.info("Setting up bot...")
        
        # Initialize services
        try:
            logger.info("Initializing API services...")
            api_key = os.getenv("GOOGLE_API_KEY", "")
            self.api_service = APIService(api_key=api_key)
            await self.api_service.initialize()
            
            # Validate service initialization
            await self.api_service.validate()
            
            if not self.api_service.api_states.get("gemini", False):
                logger.warning("Gemini API failed to initialize")
            else:
                logger.info("Gemini API initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize services: {e}", exc_info=True)
            # Continue without AI services
        
        # Add slash commands
        logger.info("Syncing slash commands...")
        try:
            await self.tree.sync()
            logger.info("Slash commands synced successfully")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")
            
        # Update initialized status
        self.initialized = True
        logger.info("Bot setup complete")
            
    async def on_ready(self) -> None:
        """Event handler for when the bot is ready"""
        logger.info(f"{self.user} is ready!")
        logger.info(f"Version: {VERSION}")
        
        # Log server info
        guilds = self.guilds
        logger.info(f"Connected to {len(guilds)} servers:")
        for guild in guilds:
            logger.info(f"- {guild.name} (ID: {guild.id}, Members: {guild.member_count})")
        
    async def on_command_error(self, ctx, error) -> None:
        """Global error handler for regular commands
        
        Args:
            ctx: Command context
            error: The raised exception
        """
        if isinstance(error, commands.CommandNotFound):
            return
        
        if isinstance(error, commands.CommandInvokeError):
            # Get the original error
            error = error.original
        
        try:
            if isinstance(error, ValueError):
                # Clean error handling for value errors (expected errors)
                embed = discord.Embed(
                    title="오류",
                    description=str(error),
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
            else:
                # Log unexpected errors
                logger.error(f"Command error in {ctx.command}: {error}", exc_info=True)
                
                # Send error message
                embed = discord.Embed(
                    title="오류가 발생했어",
                    description=f"명령어 처리 중 예상치 못한 오류가 발생했어.\n```{error}```",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                
        except Exception as e:
            # Fallback for error in error handler
            logger.error(f"Error in error handler: {e}", exc_info=True)
            try:
                await ctx.send("오류가 발생했어.")
            except:
                pass
    
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Handle button interactions
        
        Args:
            interaction: The interaction event
        """
        # Process the interaction first to avoid timeout
        if interaction.type == discord.InteractionType.application_command:
            # Let discord.py handle slash commands
            await self.process_application_commands(interaction)
            return
            
        # For component interactions like buttons
        if interaction.type == discord.InteractionType.component:
            try:
                # Check if this is a source button
                if interaction.data.get("custom_id", "").startswith("sources_"):
                    # Get source_id from custom_id
                    source_id = interaction.data.get("custom_id", "").replace("sources_", "")
                    
                    # Handle the interaction
                    await self.ai_commands.handle_button_interaction(interaction)
                    
                    # Clean up from source_storage in ai_commands
                    from src.commands.ai import source_storage
                    if source_id in source_storage:
                        del source_storage[source_id]
                    
                    return
            except Exception as e:
                logger.error(f"Error handling button interaction: {e}", exc_info=True)
                await interaction.response.send_message(
                    "버튼 처리 중 문제가 생겼어.", 
                    ephemeral=True
                )
        
    
    async def on_application_command_error(
        self, 
        ctx: discord.Interaction, 
        error: Exception
    ) -> None:
        """Global error handler for slash commands
        
        Args:
            ctx: Interaction context
            error: The raised exception
        """
        if isinstance(error, discord.app_commands.CommandInvokeError):
            # Get the original error
            error = error.original
        
        try:
            if isinstance(error, ValueError):
                # Clean error handling for value errors (expected errors)
                try:
                    await ctx.response.send_message(
                        str(error),
                        ephemeral=True
                    )
                except discord.errors.InteractionResponded:
                    # If already responded, send followup
                    await ctx.followup.send(
                        str(error),
                        ephemeral=True
                    )
            else:
                # Log unexpected errors
                logger.error(f"Slash command error: {error}", exc_info=True)
                
                # Send error message
                try:
                    await ctx.response.send_message(
                        f"명령어 처리 중 예상치 못한 오류가 발생했어.\n```{error}```",
                        ephemeral=True
                    )
                except discord.errors.InteractionResponded:
                    # If already responded, send followup
                    await ctx.followup.send(
                        f"명령어 처리 중 예상치 못한 오류가 발생했어.\n```{error}```",
                        ephemeral=True
                    )
                
        except Exception as e:
            # Fallback for error in error handler
            logger.error(f"Error in error handler: {e}", exc_info=True)
            try:
                await ctx.followup.send(
                    "오류가 발생했어.",
                    ephemeral=True
                )
            except:
                pass

def run_bot() -> None:
    """Run the Discord bot with configuration"""
    # Configure intents
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    
    # Configure bot activity
    activity = discord.Activity(
        type=discord.ActivityType.playing,
        name="with Rhine Lab experiments"
    )
    
    # Configure command prefixes
    prefixes = ['!!', 'pt ', '뮤 ', '뮤엘 ']
    
    # Initialize bot
    bot = MuelsyseBot(
        command_prefix=prefixes, 
        intents=intents,
        activity=activity,
        status=discord.Status.online
    )
    
    # Get Discord token
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        logger.error("No Discord token provided. Please set the DISCORD_TOKEN environment variable.")
        return
    
    # Run the bot
    logger.info("Starting bot...")
    bot.run(token)

if __name__ == "__main__":
    # Set up logging
    setup_logging()
    logger.info("Starting bot application...")
    
    # Run bot
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
