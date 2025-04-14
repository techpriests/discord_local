import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Type, cast, NoReturn, Union
import asyncio
import os
import time
import shutil

import discord
from discord.app_commands import AppCommandError
from discord.ext import commands
from discord import app_commands

from src.services.memory_db import MemoryDB, MemoryInfo
from src.services.message_handler import MessageHandler
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR
from src.utils.version import get_git_info, VersionInfo
from src.commands.base_commands import BaseCommands
from src.commands.information import InformationCommands
from src.commands.entertainment import EntertainmentCommands
from src.commands.system import SystemCommands
from src.commands.arknights import ArknightsCommands
from src.commands.ai import AICommands
from src.services.api.service import APIService

logger = logging.getLogger(__name__)

class DiscordBot(commands.Bot):
    """Main bot class handling commands and events"""

    def __init__(self, config: Dict[str, str], api_service: Optional[APIService] = None) -> None:
        """Initialize bot
        
        Args:
            config: Configuration dictionary containing API keys
            api_service: Optional APIService instance. If not provided, one will be created.
        """
        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # Required for member-related operations
        intents.guilds = True   # Required for guild operations
        intents.messages = True # Required for message operations
        logger.info("Initialized bot intents: %s", intents.value)

        # Initialize bot with command prefixes
        super().__init__(
            command_prefix=self._get_prefix,
            intents=intents,
            help_command=None  # Disable default help command
        )

        # Store configuration
        self._config = config
        self._api_service = api_service
        self._command_classes: List[Type[BaseCommands]] = [
            InformationCommands,
            EntertainmentCommands,
            SystemCommands,
            ArknightsCommands,
            AICommands
        ]
        self.memory_db: Optional[MemoryDB] = None
        self.version_info: VersionInfo = get_git_info()
        logger.info("Bot initialization completed")

    @property
    def api_service(self) -> APIService:
        """Get API service
        
        Returns:
            APIService: API service instance

        Raises:
            ValueError: If service not initialized
        """
        if not self._api_service:
            raise ValueError("API service not initialized")
        return self._api_service

    async def _handle_help(self, ctx_or_interaction: CommandContext) -> None:
        """Handle help command"""
        embed = discord.Embed(
            title="도움말",
            description=HELP_DESCRIPTION,
            color=INFO_COLOR
        )
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

    async def setup_hook(self) -> None:
        """Initialize bot services and register commands"""
        try:
            logger.info("Starting setup_hook...")
            
            # Initialize API service first since commands depend on it
            if not self._api_service:
                logger.info("Initializing API service...")
                try:
                    self._api_service = APIService(self._config)
                    await self._api_service.initialize(self._config)  # Pass credentials here
                    
                    # Log API states
                    api_states = self._api_service.api_states
                    logger.info("API initialization states:")
                    for api_name, state in api_states.items():
                        logger.info(f"- {api_name}: {'✓' if state else '✗'}")
                        
                except Exception as e:
                    logger.error(f"API service initialization failed: {str(e)}", exc_info=True)
                    raise ValueError(f"Failed to initialize API service: {str(e)}")
                logger.info("API service initialized successfully")
            
            # Initialize memory database
            logger.info("Initializing memory database...")
            await self._initialize_memory_db()

            # Register commands
            logger.info("Registering commands...")
            await self._register_commands()
            logger.info("Commands registered successfully")

            # Sync all commands once at the end
            logger.info("Syncing slash commands...")
            await self.tree.sync()
            logger.info("Slash commands synced successfully")

            logger.info("Bot setup completed successfully")
        except Exception as e:
            logger.error(f"Error in setup_hook: {str(e)}", exc_info=True)
            # Clean up on failure
            await self._cleanup_on_setup_failure()
            raise

    async def _cleanup_on_setup_failure(self) -> None:
        """Clean up resources if setup fails"""
        cleanup_errors = []
        
        try:
            # Clean up API service
            if self._api_service:
                logger.info("Cleaning up API service...")
                try:
                    await self._api_service.close()
                except Exception as e:
                    cleanup_errors.append(f"API service cleanup error: {e}")
                finally:
                    self._api_service = None
            
            # Clean up memory database
            if self.memory_db:
                logger.info("Cleaning up memory database...")
                try:
                    await self.memory_db.close()
                except Exception as e:
                    cleanup_errors.append(f"Memory DB cleanup error: {e}")
                finally:
                    self.memory_db = None

            # Clean up any pending tasks
            try:
                tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                if tasks:
                    logger.info(f"Cleaning up {len(tasks)} pending tasks...")
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                cleanup_errors.append(f"Task cleanup error: {e}")
                
        except Exception as e:
            cleanup_errors.append(f"General cleanup error: {e}")
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
        finally:
            # Ensure services are set to None even if cleanup fails
            self._api_service = None
            self.memory_db = None
            
            # Log all cleanup errors if any occurred
            if cleanup_errors:
                logger.error("Multiple cleanup errors occurred:\n" + "\n".join(cleanup_errors))

    async def _register_commands(self) -> None:
        """Register all command classes"""
        try:
            logger.info("Starting command registration...")
            
            # Ensure API service is initialized
            if not self._api_service or not self._api_service.initialized:
                raise ValueError("API service must be initialized before registering commands")
                
            for command_class in self._command_classes:
                try:
                    logger.info(f"Registering command class: {command_class.__name__}")
                    
                    # Initialize cog based on its requirements
                    cog = None
                    if command_class == InformationCommands:
                        cog = command_class(self.api_service)
                    elif command_class == SystemCommands:
                        cog = command_class(self)
                    elif command_class == AICommands:
                        cog = command_class()
                        cog.bot = self  # Set bot instance for API access
                    else:
                        cog = command_class()
                    
                    # Add cog and verify it was added successfully
                    await self.add_cog(cog)
                    if not self.get_cog(command_class.__name__):
                        raise ValueError(f"Failed to add cog: {command_class.__name__}")
                        
                    logger.info(f"Successfully registered {command_class.__name__}")
                except Exception as e:
                    logger.error(f"Failed to register command class {command_class.__name__}: {str(e)}")
                    raise  # Re-raise to handle in setup_hook
            
            logger.info("Command registration complete")
        except Exception as e:
            logger.error(f"Failed to register commands: {str(e)}")
            raise

    async def on_ready(self) -> None:
        """Handle bot ready event"""
        try:
            logger.info("Bot on_ready event triggered")
            user = cast(discord.ClientUser, self.user)
            logger.info(
                f"Logged in as {user.name} "
                f"(Version: {self.version_info.version}, "
                f"Commit: {self.version_info.commit}, "
                f"Branch: {self.version_info.branch})"
            )

            # Set up notification channels after bot is ready
            logger.info("Setting up notification channels...")
            notification_channels = []
            for guild in self.guilds:
                channel = discord.utils.get(guild.text_channels, name="bot-notifications")
                if channel:
                    notification_channels.append(channel)
                    logger.info(f"Found existing notification channel in {guild.name}")
                    continue
                
                try:
                    # Create channel if it doesn't exist
                    channel = await guild.create_text_channel(
                        "bot-notifications",
                        topic="AI Service Status Notifications",
                        reason="Required for bot status notifications"
                    )
                    notification_channels.append(channel)
                    logger.info(f"Created notification channel in {guild.name}")
                except discord.Forbidden:
                    logger.warning(f"Missing permissions to create notification channel in {guild.name}")
                except Exception as e:
                    logger.error(f"Failed to create notification channel in {guild.name}: {e}")

            # Update API service with notification channel if available
            if notification_channels and self._api_service:
                logger.info("Updating API service with notification channel")
                self._api_service.update_notification_channel(notification_channels[0])
                
                # Log final API states after notification channel setup
                api_states = self._api_service.api_states
                logger.info("Final API states after notification setup:")
                for api_name, state in api_states.items():
                    logger.info(f"- {api_name}: {'✓' if state else '✗'}")

            # Set bot presence
            logger.info("Setting bot presence...")
            await cast(discord.Client, self).change_presence(
                activity=discord.Game(
                    name=f"뮤 도움말 | /help | {self.version_info.commit}"
                )
            )
            logger.info("Bot initialization complete")
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)

    async def on_command_error(
        self, 
        ctx: commands.Context, 
        error: commands.CommandError
    ) -> None:
        """Handle command errors
        
        Args:
            ctx: Command context
            error: Error that occurred
        """
        if isinstance(error, commands.CommandNotFound):
            return

        error_message = self._get_error_message(error)
        await self._send_error_message(cast(CommandContext, ctx), error_message)
        logger.error(f"Command error: {error}", exc_info=error)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ) -> None:
        """Handle application command errors"""
        error_message = self._get_error_message(error)
        await self._send_error_message(interaction, error_message)
        logger.error(f"Slash command error: {error}", exc_info=error)

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Handle button interactions
        
        Args:
            interaction: The interaction event
        """
        # Process the interaction first to avoid timeout
        if interaction.type == discord.InteractionType.application_command:
            # Let discord.py handle slash commands
            return
            
        # For component interactions like buttons
        if interaction.type == discord.InteractionType.component:
            try:
                # Check if this is a source button
                if interaction.data.get("custom_id", "").startswith("sources_"):
                    # Get source_id from custom_id
                    source_id = interaction.data.get("custom_id", "").replace("sources_", "")
                    
                    # Get AICommands instance
                    ai_commands = self.get_cog("AICommands")
                    if ai_commands:
                        # Handle the interaction
                        await ai_commands.handle_button_interaction(interaction)
                        
                        # Clean up from source_storage in ai_commands
                        from src.commands.ai import source_storage
                        if source_id in source_storage:
                            del source_storage[source_id]
                    else:
                        await interaction.response.send_message(
                            "명령어를 처리할 수 없어.",
                            ephemeral=True
                        )
                    
                    return
            except Exception as e:
                logger.error(f"Error handling button interaction: {e}", exc_info=True)
                await interaction.response.send_message(
                    "버튼 처리 중 문제가 생겼어.", 
                    ephemeral=True
                )

    def _get_error_message(self, error: Exception) -> str:
        """Get user-friendly error message
        
        Args:
            error: Error to process

        Returns:
            str: Error message to display
        """
        if isinstance(error, commands.MissingPermissions):
            return "이 명령어를 실행할 권한이 없어"
        if isinstance(error, commands.BotMissingPermissions):
            return "봇에 필요한 권한이 없어"
        if isinstance(error, commands.MissingRequiredArgument):
            return f"필수 인자가 누락되었어: {error.param.name}"
        if isinstance(error, commands.BadArgument):
            return "잘못된 인자가 전달되었어"
        if isinstance(error, commands.CommandOnCooldown):
            return f"명령어 재사용 대기 시간이야. {error.retry_after:.1f}초 후에 다시 시도해줘."
        if isinstance(error, ValueError):
            return str(error)
        
        return "명령어 실행 중 오류가 발생한 것 같아"

    async def _send_error_message(
        self, 
        ctx_or_interaction: CommandContext, 
        error_message: str
    ) -> None:
        """Send error message to user
        
        Args:
            ctx_or_interaction: Command context or interaction
            error_message: Error message to send
        """
        embed = discord.Embed(
            title="❌ 오류",
            description=error_message,
            color=ERROR_COLOR
        )

        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await ctx_or_interaction.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

    async def _cleanup(self) -> None:
        """Clean up bot resources"""
        cleanup_errors = []
        
        try:
            # Clean up API service
            if self._api_service:
                try:
                    await self._api_service.close()
                except Exception as e:
                    cleanup_errors.append(f"API service cleanup error: {e}")
            
            # Clean up memory database
            if self.memory_db:
                try:
                    await self.memory_db.close()
                except Exception as e:
                    cleanup_errors.append(f"Memory DB cleanup error: {e}")
            
            # Clean up any remaining tasks
            try:
                tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                cleanup_errors.append(f"Task cleanup error: {e}")
            
        except Exception as e:
            cleanup_errors.append(f"General cleanup error: {e}")
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
            
        # Log all cleanup errors if any occurred
        if cleanup_errors:
            logger.error("Multiple cleanup errors occurred:\n" + "\n".join(cleanup_errors))

    async def close(self) -> None:
        """Close the bot connection and clean up resources"""
        try:
            logger.info("Bot shutting down, cleaning up resources...")
            
            # Clean up API service first
            if self._api_service:
                logger.info("Closing API service...")
                await self._api_service.close()
                self._api_service = None

            # Clean up memory database
            if self.memory_db:
                logger.info("Closing memory database...")
                await self.memory_db.close()
                self.memory_db = None

            # Clean up any remaining tasks
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if tasks:
                logger.info(f"Cleaning up {len(tasks)} remaining tasks...")
                await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
        finally:
            await super().close()
            logger.info("Bot shutdown complete")

    @commands.command(name="환율")
    async def exchange_prefix(
        self,
        ctx: commands.Context,
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> None:
        """Show exchange rates"""
        await self._handle_exchange(ctx, currency, amount)

    @app_commands.command(name="exchange", description="환율 정보를 보여줍니다")
    async def exchange_slash(
        self,
        interaction: discord.Interaction,
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> None:
        """Show exchange rates"""
        await self._handle_exchange(interaction, currency, amount)

    async def _handle_exchange(
        self,
        ctx_or_interaction: CommandContext,
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> None:
        """Handle exchange rate command"""
        try:
            self._validate_amount(amount)
            rates = await self.api_service.exchange.get_exchange_rates()
            embed = await self._create_exchange_embed(rates, currency, amount)
            await self._send_response(ctx_or_interaction, embed=embed)
        except ValueError as e:
            raise e
        except Exception as e:
            logger.error(f"Unexpected error in exchange command: {e}")
            raise ValueError("예상치 못한 오류가 발생했어") from e

    def _validate_amount(self, amount: float) -> None:
        """Validate exchange amount

        Args:
            amount: Amount to validate

        Raises:
            ValueError: If amount is invalid
        """
        if amount <= 0:
            raise ValueError("금액은 0보다 커야 합니다")
        if amount > 1000000000:
            raise ValueError("금액이 너무 큽니다 (최대: 1,000,000,000)")

    async def _get_exchange_rates(self) -> Dict[str, float]:
        """Get current exchange rates"""
        try:
            return await self.api_service.exchange.get_exchange_rates()
        except Exception as e:
            logger.error(f"Failed to get exchange rates: {e}")
            raise ValueError("환율 정보를 가져오는데 실패했어") from e

    async def _create_exchange_embed(
        self,
        rates: Dict[str, float],
        currency: Optional[str] = None,
        amount: float = 1.0
    ) -> discord.Embed:
        """Create exchange rate embed
        
        Args:
            rates: Exchange rates
            currency: Optional specific currency
            amount: Amount to convert

        Returns:
            discord.Embed: Formatted embed
        """
        embed = discord.Embed(
            title="💱 환율 정보",
            color=INFO_COLOR,
            timestamp=datetime.now()
        )

        if currency:
            if currency.upper() not in rates:
                raise ValueError(f"지원하지 않는 통화입니다: {currency}")
            rate = rates[currency.upper()]
            embed.add_field(
                name=f"KRW → {currency.upper()}",
                value=f"{amount:,.0f} KRW = {amount/rate:,.2f} {currency.upper()}",
                inline=False
            )
        else:
            for curr, rate in rates.items():
                embed.add_field(
                    name=f"KRW → {curr}",
                    value=f"{amount:,.0f} KRW = {amount/rate:,.2f} {curr}",
                    inline=True
                )

        return embed

    @discord.app_commands.command(name="remember", description="정보를 기억합니다")
    async def remember_slash(
        self,
        interaction: discord.Interaction,
        text: str,
        nickname: str
    ) -> None:
        """Remember information for a nickname"""
        await self._handle_remember(interaction, text, nickname)

    @commands.command(name="기억")
    async def remember_prefix(
        self,
        ctx: commands.Context,
        text: str,
        nickname: str
    ) -> None:
        """Remember information for a nickname"""
        await self._handle_remember(ctx, text, nickname)

    async def _handle_remember(
        self,
        ctx_or_interaction: CommandContext,
        text: str,
        nickname: str
    ) -> None:
        """Handle remember command
        
        Args:
            ctx_or_interaction: Command context or interaction
            text: Text to remember
            nickname: Nickname to associate with text
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)
            
            await self.memory_db.store(nickname, text)
            await self._send_remember_success_message(
                ctx_or_interaction,
                nickname,
                text,
                processing_msg
            )
        except Exception as e:
            logger.error(f"Error in remember command: {e}")
            await self._send_format_error_message(ctx_or_interaction, processing_msg)

    async def _show_processing_message(
        self,
        ctx_or_interaction: CommandContext
    ) -> Optional[discord.Message]:
        """Show processing message
        
        Args:
            ctx_or_interaction: Command context or interaction

        Returns:
            Optional[discord.Message]: Processing message if sent
        """
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.defer()
                return None
            else:
                return await ctx_or_interaction.send("처리 중...")
        except Exception as e:
            logger.error(f"Error showing processing message: {e}")
            return None

    async def _send_remember_success_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        text: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send success message for remember command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that was remembered
            text: Text that was stored
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 정보를 기억했어: {text}"
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @discord.app_commands.command(name="recall", description="정보를 알려줍니다")
    async def recall_slash(
        self,
        interaction: discord.Interaction,
        nickname: str
    ) -> None:
        """Recall information for a nickname"""
        await self._handle_recall(interaction, nickname)

    @commands.command(name="알려")
    async def recall_prefix(
        self,
        ctx: commands.Context,
        nickname: str
    ) -> None:
        """Recall information for a nickname"""
        await self._handle_recall(ctx, nickname)

    async def _handle_recall(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str
    ) -> None:
        """Handle recall command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname to recall information for
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)
            memories = await self.memory_db.recall(nickname)

            if memories:
                await self._send_memories_embed(
                    ctx_or_interaction,
                    nickname,
                    memories,
                    processing_msg
                )
            else:
                await self._send_no_memories_message(
                    ctx_or_interaction,
                    nickname,
                    processing_msg
                )

        except Exception as e:
            logger.error(f"Error in recall command: {e}")
            await self._send_error_message(ctx_or_interaction, str(e))

    async def _send_memories_embed(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        memories: Dict[str, MemoryInfo],
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send embed with memories
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname of memories
            memories: Memory information
            processing_msg: Optional processing message to delete
        """
        embed = discord.Embed(
            title=f"{nickname}의 정보",
            color=INFO_COLOR
        )

        for memory in memories.values():
            embed.add_field(
                name=memory["text"],
                value=f"입력: {memory['author']}\n시간: {memory['timestamp']}",
                inline=False
            )

        await self._send_response(ctx_or_interaction, embed=embed)
        if processing_msg:
            await processing_msg.delete()

    async def _send_no_memories_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send message when no memories found
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that had no memories
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 기억이 없어."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @discord.app_commands.command(name="forget", description="정보를 잊어버립니다")
    async def forget_slash(
        self,
        interaction: discord.Interaction,
        nickname: str
    ) -> None:
        """Forget information for a nickname"""
        await self._handle_forget(interaction, nickname)

    @commands.command(name="잊어")
    async def forget_prefix(
        self,
        ctx: commands.Context,
        nickname: str
    ) -> None:
        """Forget information for a nickname"""
        await self._handle_forget(ctx, nickname)

    async def _handle_forget(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str
    ) -> None:
        """Handle forget command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname to forget information for
        """
        try:
            processing_msg = await self._show_processing_message(ctx_or_interaction)

            if await self.memory_db.forget(nickname):
                await self._send_forget_success_message(
                    ctx_or_interaction,
                    nickname,
                    processing_msg
                )
            else:
                await self._send_forget_not_found_message(
                    ctx_or_interaction,
                    nickname,
                    processing_msg
                )

        except Exception as e:
            logger.error(f"Error in forget command: {e}")
            await self._send_format_error_message(ctx_or_interaction, processing_msg)

    async def _send_forget_success_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send success message for forget command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that was forgotten
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 모든 정보를 삭제했어."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    async def _send_forget_not_found_message(
        self,
        ctx_or_interaction: CommandContext,
        nickname: str,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send not found message for forget command
        
        Args:
            ctx_or_interaction: Command context or interaction
            nickname: Nickname that wasn't found
            processing_msg: Optional processing message to delete
        """
        message = f"'{nickname}'에 대한 정보를 찾을 수 없어."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    @commands.command(
        name="help",
        help="봇의 도움말을 보여줍니다",
        brief="도움말 보기",
        aliases=["muhelp", "도움말", "도움", "명령어"],
        description="봇의 모든 명령어와 사용법을 보여줍니다.\n"
        "사용법:\n"
        "• !!help\n"
        "• 뮤 help\n"
        "• pt help"
    )
    async def help_prefix(self, ctx: commands.Context) -> None:
        """Show help information"""
        await self._handle_help(ctx)

    @app_commands.command(name="help", description="봇의 도움말을 보여줍니다")
    async def help_slash(self, interaction: discord.Interaction) -> None:
        """Show help information"""
        await self._handle_help(interaction)

    @app_commands.command(name="memory", description="메모리 관리")
    async def memory_slash(
        self, 
        interaction: discord.Interaction,
        command_name: str,
        *,
        text: Optional[str] = None
    ) -> None:
        """Memory management command"""
        await self._handle_memory(interaction, command_name, text)

    @commands.command(name="기억", aliases=["memory"])
    async def memory_prefix(
        self,
        ctx: commands.Context,
        command_name: str,
        *,
        text: Optional[str] = None
    ) -> None:
        """Memory management command"""
        await self._handle_memory(ctx, command_name, text)

    async def _handle_memory(
        self,
        ctx_or_interaction: CommandContext,
        command_name: str,
        text: Optional[str] = None
    ) -> None:
        """Handle memory command"""
        try:
            if command_name == "저장":
                await self._store_memory(ctx_or_interaction, text)
            elif command_name == "목록":
                await self._list_memories(ctx_or_interaction)
            else:
                raise ValueError("알 수 없는 명령어입니다")
        except Exception as e:
            logger.error(f"Memory command error: {e}")
            raise ValueError("메모리 명령어 처리 중 오류가 발생했어") from e

    async def _store_memory(
        self,
        ctx_or_interaction: CommandContext,
        text: Optional[str]
    ) -> None:
        """Store memory for user"""
        if not self.memory_db:
            await self._initialize_memory_db()
        if not text:
            raise ValueError("저장할 내용을 입력해주세요")

        user_name = self.get_user_name(ctx_or_interaction)
        await self.memory_db.store(user_name, text)
        await self._send_response(
            ctx_or_interaction,
            f"'{text}' 를 기억했어!"
        )

    async def _initialize_memory_db(self) -> None:
        """Initialize memory database"""
        try:
            logger.info("Initializing memory database...")
            # Ensure data directory exists
            os.makedirs("data", exist_ok=True)
            
            # Create and test database
            self.memory_db = MemoryDB()
            
            # Validate database access with test operations
            test_key = f"test_{int(time.time())}"
            await self.memory_db.store(test_key, "Initialization test", "system")
            test_data = await self.memory_db.recall(test_key)
            if not test_data:
                raise ValueError("Failed to verify database read/write access")
            await self.memory_db.forget(test_key)
            
            logger.info("Memory database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize memory database: {e}")
            if hasattr(self, 'memory_db') and self.memory_db:
                await self.memory_db.close()
            self.memory_db = None
            raise ValueError(f"Memory database initialization failed: {str(e)}")

    async def _list_memories(self, ctx_or_interaction: CommandContext) -> None:
        """List memories for user"""
        if not self.memory_db:
            raise ValueError("Memory DB not initialized")

        user_name = self.get_user_name(ctx_or_interaction)
        memories = await self.memory_db.recall(user_name)
        
        if not memories:
            await self._send_response(
                ctx_or_interaction,
                "저장된 기억이 없어."
            )
            return

        embed = discord.Embed(
            title=f"{user_name}님의 기억",
            color=INFO_COLOR
        )
        for memory_id, memory in memories.items():
            embed.add_field(
                name=memory["timestamp"],
                value=memory["text"],
                inline=False
            )
        await self._send_response(ctx_or_interaction, embed=embed)

    @commands.command(name="동기화", help="슬래시 명령어를 동기화합니다")
    @commands.has_permissions(administrator=True)
    async def sync(self, ctx: commands.Context) -> None:
        """Synchronize slash commands (admin only)
        
        Args:
            ctx: Command context
        """
        try:
            await self.tree.sync()
            await ctx.send("슬래시 명령어 동기화 완료!")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            raise ValueError("명령어 동기화에 실패했어") from e

    @commands.command(name="리로드", help="명령어 모듈을 다시 로드합니다")
    @commands.is_owner()  # Only bot owner can use this
    async def reload(self, ctx: commands.Context, module: Optional[str] = None) -> None:
        """Reload command modules (owner only)
        
        Args:
            ctx: Command context
            module: Optional module name to reload, reloads all if not specified
        """
        try:
            # Track reload outcomes
            success_modules = []
            failed_modules = {}
            
            if module:
                # Reload specific module
                found = False
                for cmd_class in self._command_classes:
                    if cmd_class.__name__.lower() == module.lower():
                        found = True
                        cog_name = cmd_class.__name__
                        
                        try:
                            # Remove existing cog
                            if self.get_cog(cog_name):
                                await self.remove_cog(cog_name)
                            
                            # Re-initialize and add the cog
                            if cmd_class == InformationCommands:
                                cog = cmd_class(self.api_service)
                            elif cmd_class == SystemCommands:
                                cog = cmd_class(self)
                            elif cmd_class == AICommands:
                                cog = cmd_class()
                                cog.bot = self
                            else:
                                cog = cmd_class()
                                
                            await self.add_cog(cog)
                            success_modules.append(cog_name)
                        except Exception as e:
                            logger.error(f"Failed to reload {cog_name}: {e}", exc_info=True)
                            failed_modules[cog_name] = str(e)
                        
                        break
                
                if not found:
                    await ctx.send(f"모듈 '{module}'을(를) 찾을 수 없어.")
                    return
            else:
                # Reload all modules
                for cmd_class in self._command_classes:
                    cog_name = cmd_class.__name__
                    try:
                        # Remove existing cog
                        if self.get_cog(cog_name):
                            await self.remove_cog(cog_name)
                        
                        # Re-initialize and add the cog with specific initialization
                        if cmd_class == InformationCommands:
                            cog = cmd_class(self.api_service)
                        elif cmd_class == SystemCommands:
                            cog = cmd_class(self)
                        elif cmd_class == AICommands:
                            cog = cmd_class()
                            cog.bot = self
                        else:
                            cog = cmd_class()
                            
                        await self.add_cog(cog)
                        success_modules.append(cog_name)
                    except Exception as e:
                        logger.error(f"Failed to reload {cog_name}: {e}", exc_info=True)
                        failed_modules[cog_name] = str(e)
            
            # Try to sync slash commands (but don't fail if it doesn't work)
            try:
                await self.tree.sync()
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")
                failed_modules["CommandSync"] = str(e)
            
            # Clear update notification if exists
            update_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "updates.txt")
            update_info = None
            if os.path.exists(update_file):
                with open(update_file, 'r') as f:
                    update_info = f.read().strip()
                os.remove(update_file)
                await ctx.send("업데이트가 성공적으로 적용되었어.")
            
            # Update version info if hot reload version file exists
            hot_reload_version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                                 "hot_reload_version.txt")
            if os.path.exists(hot_reload_version_file):
                try:
                    with open(hot_reload_version_file, 'r') as f:
                        new_commit = f.read().strip()
                    
                    # Only update if we have a valid commit hash
                    if new_commit and len(new_commit) >= 7:
                        # Create a new VersionInfo with updated commit
                        from src.utils.version import VersionInfo
                        self.version_info = VersionInfo(
                            version=self.version_info.version,
                            commit=new_commit[:7],  # Use first 7 chars of commit hash
                            branch=self.version_info.branch
                        )
                        
                        # Update bot presence with new commit info
                        await cast(discord.Client, self).change_presence(
                            activity=discord.Game(
                                name=f"뮤 도움말 | /help | {self.version_info.commit}"
                            )
                        )
                        
                        logger.info(f"Version info updated to: {self.version_info.commit}")
                except Exception as e:
                    logger.error(f"Failed to update version info: {e}")
            
            # Send detailed report
            if success_modules and not failed_modules:
                # All modules reloaded successfully
                modules_str = ", ".join(success_modules)
                await ctx.send(f"✅ 모든 모듈이 성공적으로 리로드됐어: {modules_str}")
            elif success_modules and failed_modules:
                # Some modules failed, some succeeded
                success_str = ", ".join(success_modules)
                failed_str = ", ".join(failed_modules.keys())
                
                # Just show a summary instead of detailed errors
                await ctx.send(f"⚠️ 일부 모듈만 리로드됐어.\n✅ 성공: {success_str}\n❌ 실패: {failed_str}")
            else:
                # All modules failed
                failed_str = ", ".join(failed_modules.keys())
                await ctx.send(f"❌ 모든 모듈 리로드에 실패했어. 실패한 모듈: {failed_str}")
            
        except Exception as e:
            logger.error(f"Failed to reload modules: {e}", exc_info=True)
            await ctx.send(f"모듈 리로드 중 오류가 발생했어: {str(e)}")

    @commands.command(name="업데이트확인", help="새 업데이트 확인")
    @commands.is_owner()  # Only bot owner can use this
    async def check_updates(self, ctx: commands.Context) -> None:
        """Check if updates are available and notify the owner"""
        try:
            update_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "updates.txt")
            if os.path.exists(update_file):
                with open(update_file, 'r') as f:
                    update_info = f.read().strip()
                
                # Send notification with reload instructions
                await ctx.send(f"**업데이트가 준비되었어**\n```\n{update_info}\n```\n적용하려면 `!!리로드` 명령어를 사용해줘.")
            else:
                await ctx.send("새 업데이트가 없어.")
        except Exception as e:
            logger.error(f"Failed to check updates: {e}")
            await ctx.send(f"업데이트 확인 중 오류가 발생했어. 오류: {str(e)}")

    @commands.command(name="롤백", help="이전 버전으로 롤백합니다")
    @commands.is_owner()  # Only bot owner can use this
    async def rollback(self, ctx: commands.Context) -> None:
        """Rollback to previous version (owner only)"""
        from datetime import datetime, timedelta
        
        # Define paths
        base_dir = os.path.dirname(os.path.dirname(__file__))
        lock_file = os.path.join(base_dir, "rollback.lock")
        backup_info_file = os.path.join(base_dir, "current_backup.txt")
        temp_restore_dir = None
        
        try:
            # Check for concurrent operations
            if os.path.exists(lock_file):
                try:
                    last_modified = datetime.fromtimestamp(os.path.getmtime(lock_file))
                    if datetime.now() - last_modified < timedelta(minutes=10):
                        await ctx.send("⚠️ 응? 이미 다른 롤백이나 업데이트 작업이 진행 중인데? 조금만 기다려줘.")
                        return
                    # Lock file exists but old (>10 min), assume stale and continue
                    logger.warning("Removing stale rollback lock file")
                except Exception as e:
                    logger.error(f"Error checking lock file: {e}")
            
            # Create lock file
            with open(lock_file, "w") as f:
                f.write(f"Rollback started by {ctx.author} at {datetime.now().isoformat()}")
            
            # Check for deployment lock
            deployment_lock = os.path.join(base_dir, "update.lock")
            if os.path.exists(deployment_lock):
                try:
                    last_modified = datetime.fromtimestamp(os.path.getmtime(deployment_lock))
                    if datetime.now() - last_modified < timedelta(minutes=5):
                        await ctx.send("⚠️ 지금 배포 작업이 진행 중이야! 조금만 더 기다려줘.")
                        return
                except Exception:
                    pass  # Continue if we can't check the file
            
            # Check for current backup info
            if not os.path.exists(backup_info_file):
                await ctx.send("음... 롤백할 백업 정보가 없는데? 백업부터 해야 되는 거 아닌가?")
                return
                
            # Read backup timestamp
            with open(backup_info_file, 'r') as f:
                backup_timestamp = f.read().strip()
                
            backup_dir = os.path.join(base_dir, f"src_backup_{backup_timestamp}")
            
            if not os.path.exists(backup_dir):
                await ctx.send(f"이상한데? 백업 디렉토리를 찾을 수 없어: {backup_dir}. 이전 실험 기록이 사라진 것 같네.")
                return
            
            # Verify backup integrity
            integrity_verified = False
            verification_message = None
            try:
                # Check file count if available
                count_file = os.path.join(backup_dir, "file_count.txt")
                if os.path.exists(count_file):
                    with open(count_file, 'r') as f:
                        expected_count = int(f.read().strip())
                    
                    actual_count = 0
                    for root, _, files in os.walk(backup_dir):
                        actual_count += sum(1 for f in files if f.endswith('.py'))
                    
                    if actual_count < expected_count * 0.9:  # Allow 10% leeway
                        verification_message = f"⚠️ 흠... 백업이 완전하지 않은 것 같은데? 예상 파일: {expected_count}개, 실제로 있는 파일: {actual_count}개."
                    else:
                        integrity_verified = True
            except Exception as e:
                logger.error(f"Error verifying backup integrity: {e}")
                verification_message = "⚠️ 백업 무결성 검증이 안 되네? 뭔가 이상한데... 그래도 계속할래?"
            
            # Confirm with user, including integrity warning if any
            confirm_message = f"**{backup_timestamp}** 백업으로 롤백할까? 계속하려면 10초 안에 👍 반응을 추가해줘!"
            if verification_message:
                confirm_message = f"{verification_message}\n{confirm_message}"
                
            confirm_msg = await ctx.send(confirm_message)
            
            # Add confirmation reaction
            await confirm_msg.add_reaction("👍")
            
            def check(reaction, user):
                return (
                    user == ctx.author 
                    and str(reaction.emoji) == "👍" 
                    and reaction.message.id == confirm_msg.id
                )
            
            try:
                # Wait for confirmation
                await self.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("롤백이 취소됐어. 현재 상태가 더 좋을지도 모르니까.")
                return
                
            # Perform rollback
            await ctx.send("롤백 진행 중... 이전 버전으로 돌아가는 중이야. 잠시만 기다려줘!")
            
            # Create temp directory for staged restore
            temp_restore_dir = os.path.join(base_dir, f"temp_restore_{int(time.time())}")
            os.makedirs(temp_restore_dir, exist_ok=True)
            
            # Create directories in temp location
            temp_commands_dir = os.path.join(temp_restore_dir, "commands")
            temp_services_dir = os.path.join(temp_restore_dir, "services")
            temp_utils_dir = os.path.join(temp_restore_dir, "utils")
            
            os.makedirs(temp_commands_dir, exist_ok=True)
            os.makedirs(temp_services_dir, exist_ok=True)
            os.makedirs(temp_utils_dir, exist_ok=True)
            
            # First copy backup files to temporary location
            backup_commands = os.path.join(backup_dir, "commands")
            backup_services = os.path.join(backup_dir, "services")
            backup_utils = os.path.join(backup_dir, "utils")
            
            # Copy files to temp directory first using shutil
            if os.path.exists(backup_commands):
                for item in os.listdir(backup_commands):
                    src_item = os.path.join(backup_commands, item)
                    dst_item = os.path.join(temp_commands_dir, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            
            if os.path.exists(backup_services):
                for item in os.listdir(backup_services):
                    src_item = os.path.join(backup_services, item)
                    dst_item = os.path.join(temp_services_dir, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            
            if os.path.exists(backup_utils):
                for item in os.listdir(backup_utils):
                    src_item = os.path.join(backup_utils, item)
                    dst_item = os.path.join(temp_utils_dir, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
            
            # Verify the temp restore contains files
            temp_file_count = 0
            for root, _, files in os.walk(temp_restore_dir):
                temp_file_count += len(files)
            
            if temp_file_count == 0:
                await ctx.send("⚠️ 임시 복원 디렉토리에 파일이 하나도 없어. 롤백을 취소할게.")
                return
            
            # If verification passed, copy from temp to actual src dirs
            src_dir = os.path.join(base_dir, "src")
            src_commands_dir = os.path.join(src_dir, "commands")
            src_services_dir = os.path.join(src_dir, "services")
            src_utils_dir = os.path.join(src_dir, "utils")
            
            # Now copy from temp to actual src with shutil
            for item in os.listdir(temp_commands_dir):
                src_item = os.path.join(temp_commands_dir, item)
                dst_item = os.path.join(src_commands_dir, item)
                if os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            for item in os.listdir(temp_services_dir):
                src_item = os.path.join(temp_services_dir, item)
                dst_item = os.path.join(src_services_dir, item)
                if os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            for item in os.listdir(temp_utils_dir):
                src_item = os.path.join(temp_utils_dir, item)
                dst_item = os.path.join(src_utils_dir, item)
                if os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            # Now reload all modules
            reload_success = True
            reload_errors = []
            
            for cmd_class in self._command_classes:
                try:
                    cog_name = cmd_class.__name__
                    if self.get_cog(cog_name):
                        await self.remove_cog(cog_name)
                except Exception as e:
                    reload_success = False
                    reload_errors.append(f"{cmd_class.__name__}: {str(e)}")
            
            # Re-register all commands
            try:
                await self._register_commands()
            except Exception as e:
                reload_success = False
                reload_errors.append(f"Command registration: {str(e)}")
            
            # Sync slash commands
            try:
                await self.tree.sync()
            except Exception as e:
                logger.error(f"Failed to sync commands after rollback: {e}")
                # Don't fail the rollback just because sync failed
            
            # Delete the hot reload version file if it exists
            hot_reload_version_file = os.path.join(base_dir, "hot_reload_version.txt")
            if os.path.exists(hot_reload_version_file):
                os.remove(hot_reload_version_file)
            
            # Remove current backup marker only if reload succeeded
            if reload_success:
                os.remove(backup_info_file)
                await ctx.send(f"**{backup_timestamp}** 백업으로 롤백 완료! 모든 명령어가 다시 로드됐어.")
            else:
                error_details = "\n".join(reload_errors[:5])  # Show first 5 errors
                await ctx.send(f"⚠️ 흠, 이상한데? 파일은 복원됐지만 일부 모듈이 제대로 로드되지 않았어:\n```{error_details}```\n문제가 계속되면 완전히 재시작해야 할 것 같아.")
            
        except Exception as e:
            logger.error(f"Failed to rollback: {e}", exc_info=True)
            await ctx.send(f"롤백 도중에 문제가 생겼어. 오류: {str(e)}")
        finally:
            # Cleanup temp directory
            if temp_restore_dir and os.path.exists(temp_restore_dir):
                try:
                    shutil.rmtree(temp_restore_dir)
                except Exception as e:
                    logger.error(f"Failed to remove temp directory: {e}")
            
            # Always remove lock file
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
            except Exception as e:
                logger.error(f"Failed to remove lock file: {e}")

    @commands.command(name="백업확인", help="사용 가능한 백업 확인")
    @commands.is_owner()  # Only bot owner can use this
    async def check_backups(self, ctx: commands.Context) -> None:
        """Check available backups (owner only)"""
        try:
            base_dir = os.path.dirname(os.path.dirname(__file__))
            
            # List all backup directories
            backup_dirs = [d for d in os.listdir(base_dir) if d.startswith("src_backup_")]
            
            if not backup_dirs:
                await ctx.send("아직 사용할 수 있는 백업이 없어.")
                return
                
            # Sort by timestamp (newest first)
            backup_dirs.sort(reverse=True)
            
            # Format and send message
            backup_list = "\n".join([
                f"{i+1}. {d.replace('src_backup_', '')}" 
                for i, d in enumerate(backup_dirs[:10])  # Show at most 10
            ])
            
            # Check if current_backup.txt exists and read its content
            current_backup = "없음"
            backup_info_file = os.path.join(base_dir, "current_backup.txt")
            if os.path.exists(backup_info_file):
                with open(backup_info_file, 'r') as f:
                    current_backup = f.read().strip()
            
            await ctx.send(f"**사용 가능한 백업:**\n```\n{backup_list}\n```\n**현재 롤백 가능한 백업:** {current_backup}")
            
        except Exception as e:
            logger.error(f"Failed to check backups: {e}")
            await ctx.send(f"백업 확인 중에 문제가 생겼어. 오류: {str(e)}")

    @commands.command(name="긴급종료", help="긴급 상황에서 봇을 안전하게 종료합니다")
    @commands.is_owner()  # Strictly owner-only
    async def emergency_shutdown(self, ctx: commands.Context, *, reason: str = "긴급 종료 요청") -> None:
        """Emergency shutdown in case of critical failures (owner only)
        
        Args:
            ctx: Command context
            reason: Reason for emergency shutdown
        """
        try:
            # Confirm with user
            confirm_msg = await ctx.send(f"⚠️ **주의! 긴급 종료 프로토콜을 실행할까?**\n"
                                        f"이유: {reason}\n\n"
                                        f"정말로 실험을 멈추려면 👍 반응을 추가해줘. 취소하려면 무시하면 돼!")
            
            await confirm_msg.add_reaction("👍")
            
            def check(reaction, user):
                return (user == ctx.author and 
                        str(reaction.emoji) == "👍" and 
                        reaction.message.id == confirm_msg.id)
            
            try:
                # Wait for confirmation
                await self.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("긴급 종료가 취소됐어.")
                return
            
            # Log the shutdown
            logger.critical(f"EMERGENCY SHUTDOWN triggered by {ctx.author} - Reason: {reason}")
            
            # Final confirmation to owner only
            await ctx.send("⚠️ 장비 종료 중... 다음에 봐!", delete_after=10)
            
            # Schedule shutdown after sending response
            self.loop.call_later(2, self._emergency_exit, reason)
        
        except Exception as e:
            logger.error(f"Failed to execute emergency shutdown: {e}")
            await ctx.send(f"긴급 종료 실행 중에 문제가 생겼어. 오류: {str(e)}")
    
    def _emergency_exit(self, reason: str) -> None:
        """Perform actual shutdown with proper cleanup
        
        Args:
            reason: Shutdown reason for logs
        """
        logger.critical(f"Executing emergency shutdown: {reason}")
        
        try:
            # Try graceful shutdown first
            task = asyncio.create_task(self.close())
            
            # Set a timeout for clean shutdown
            def force_exit():
                logger.critical("Graceful shutdown timed out. Forcing exit.")
                # Force exit
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)
                
            # Force exit after 10 seconds if graceful shutdown doesn't complete
            self.loop.call_later(10, force_exit)
        
        except Exception as e:
            logger.critical(f"Error during emergency shutdown: {e}")
            # Force shutdown as last resort
            import sys
            sys.exit(1)

    def get_user_name(self, ctx_or_interaction: CommandContext) -> str:
        """Get username from context or interaction"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.user.name
        return ctx_or_interaction.author.name

    def get_user_id(self, ctx_or_interaction: CommandContext) -> int:
        """Get user ID from context or interaction"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            return ctx_or_interaction.user.id
        return ctx_or_interaction.author.id

    async def _send_response(
        self,
        ctx_or_interaction: CommandContext,
        content: Optional[str] = None,
        *,
        embed: Optional[discord.Embed] = None,
        ephemeral: bool = False
    ) -> None:
        """Send response to user"""
        try:
            # Don't create empty embed if none provided
            if not content and not embed:
                raise ValueError("Either content or embed must be provided")

            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(
                        content=content,
                        embed=embed,
                        ephemeral=ephemeral
                    )
                else:
                    await ctx_or_interaction.response.send_message(
                        content=content,
                        embed=embed,
                        ephemeral=ephemeral
                    )
            else:
                await ctx_or_interaction.send(
                    content=content,
                    embed=embed
                )
        except Exception as e:
            logger.error(f"Failed to send response: {e}")
            raise

    async def _send_format_error_message(
        self,
        ctx_or_interaction: CommandContext,
        processing_msg: Optional[discord.Message] = None
    ) -> None:
        """Send format error message
        
        Args:
            ctx_or_interaction: Command context or interaction
            processing_msg: Optional processing message to delete
        """
        message = "올바른 형식이 아닙니다. '!!muhelp'를 참고해주세요."
        await self._send_response(ctx_or_interaction, message)
        if processing_msg:
            await processing_msg.delete()

    async def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> List[str]:
        """Get command prefixes for the bot
        
        Args:
            bot: Bot instance
            message: Message to check
            
        Returns:
            List[str]: List of valid prefixes
        """
        # Return multiple prefix options
        return ['!!', '뮤 ', 'pt ']  # Note the space after 뮤 and pt
