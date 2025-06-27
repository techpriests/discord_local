import asyncio
import logging
from typing import Dict, Optional, List, Tuple, Any
import discord

from src.services.api.exchange import ExchangeAPI
from src.services.api.population import PopulationAPI
from src.services.api.steam import SteamAPI
from src.services.api.claude import ClaudeAPI
from src.services.api.base import BaseAPI
from src.services.api.dnf import DNFAPI

logger = logging.getLogger(__name__)

class APIService:
    """Service for managing various API clients"""

    def __init__(
        self, 
        config: Dict[str, str], 
        notification_channel: Optional[discord.TextChannel] = None
    ) -> None:
        """Initialize API service with configuration

        Args:
            config: Dictionary containing API keys and settings
            notification_channel: Optional Discord channel for notifications

        Raises:
            ValueError: If required API keys are missing
        """
        logger.info("Initializing API service with config keys: %s", list(config.keys()))
        self._config = config
        self._notification_channel = notification_channel
        
        # Initialize API clients as None
        self._steam_api: Optional[SteamAPI] = None
        self._population_api: Optional[PopulationAPI] = None
        self._exchange_api: Optional[ExchangeAPI] = None
        self._claude_api: Optional[ClaudeAPI] = None
        self._dnf_api: Optional[DNFAPI] = None
        
        # Track initialization state
        self._initialized = False
        self._api_states = {
            "steam": False,
            "population": False,
            "exchange": False,
            "claude": False,
            "dnf": False
        }
        logger.info("API service instance created with initial states: %s", self._api_states)

    @property
    def api_states(self) -> Dict[str, bool]:
        """Get initialization state of each API
        
        Returns:
            Dict[str, bool]: Dictionary of API initialization states
        """
        return self._api_states.copy()

    @property
    def initialized(self) -> bool:
        """Check if API service is initialized
        
        Returns:
            bool: True if initialized
        """
        return self._initialized

    def _ensure_initialized(self) -> None:
        """Ensure API service is initialized
        
        Raises:
            ValueError: If not initialized
        """
        if not self._initialized:
            raise ValueError("API service is not initialized")

    def _get_required_key(self, config: Dict[str, str], key: str) -> str:
        """Get required key from config

        Args:
            config: Configuration dictionary
            key: Key to retrieve

        Returns:
            str: Value for the key

        Raises:
            KeyError: If key is missing or empty
        """
        value = config.get(key)
        logger.info("Checking required key %s: %s", key, "Present" if value else "Missing")
        if not value:
            logger.error("Required key %s is missing or empty", key)
            raise KeyError(f"{key} is required")
        return value

    @property
    def steam(self) -> SteamAPI:
        """Get Steam API client
        
        Returns:
            SteamAPI: Steam API client
            
        Raises:
            ValueError: If Steam API is not initialized
        """
        self._ensure_initialized()
        if not self._steam_api:
            raise ValueError("Steam API is not initialized")
        return self._steam_api

    @property
    def population(self) -> PopulationAPI:
        """Get population API client
        
        Returns:
            PopulationAPI: Population API client
            
        Raises:
            ValueError: If population API is not initialized
        """
        self._ensure_initialized()
        if not self._population_api:
            raise ValueError("Population API is not initialized")
        return self._population_api

    @property
    def exchange(self) -> ExchangeAPI:
        """Get exchange API client
        
        Returns:
            ExchangeAPI: Exchange API client
            
        Raises:
            ValueError: If exchange API is not initialized
        """
        self._ensure_initialized()
        if not self._exchange_api:
            raise ValueError("Exchange API is not initialized")
        return self._exchange_api

    @property
    def claude_api(self) -> Optional[ClaudeAPI]:
        """Get Claude API client
        
        Returns:
            Optional[ClaudeAPI]: Claude API client or None if not available
        """
        return self._claude_api

    @property
    def claude(self) -> ClaudeAPI:
        """Get Claude API client
        
        Returns:
            ClaudeAPI: Claude API client
            
        Raises:
            ValueError: If Claude API is not initialized
        """
        self._ensure_initialized()
        if not self._claude_api:
            raise ValueError("Claude API is not available - API key not provided")
        return self._claude_api

    def dnf(self) -> DNFAPI:
        """Get DNF API client

        Returns:
            DNFAPI: DNF API client

        Raises:
            ValueError: If DNF API is not initialized
        """
        if not self._dnf_api:
            raise ValueError("DNF API is not initialized")
        return self._dnf_api

    async def initialize(self, credentials: Dict[str, Any]) -> None:
        """Initialize API clients"""
        try:
            # Initialize Steam API
            steam_key = self._get_required_key(credentials, "STEAM_API_KEY")
            self._steam_api = SteamAPI(steam_key)
            await self._steam_api.initialize()
            self._api_states["steam"] = True
            logger.info("Initialized Steam API")

            # Initialize Population API (no credentials needed)
            self._population_api = PopulationAPI()
            await self._population_api.initialize()
            self._api_states["population"] = True
            logger.info("Initialized Population API")

            # Initialize Exchange API (no credentials needed)
            self._exchange_api = ExchangeAPI()
            await self._exchange_api.initialize()
            self._api_states["exchange"] = True
            logger.info("Initialized Exchange API")

            # Initialize Claude API if credentials provided
            if "CL_API_KEY" in credentials:
                self._claude_api = ClaudeAPI(
                    credentials["CL_API_KEY"],
                    self._notification_channel
                )
                await self._claude_api.initialize()
                self._api_states["claude"] = True
                logger.info("Initialized Claude API")

            # Initialize DNF API with Neople API key
            if "NEOPLE_API_KEY" in credentials:
                self._dnf_api = DNFAPI(credentials["NEOPLE_API_KEY"])
                await self._dnf_api.initialize()
                self._api_states["dnf"] = True
                logger.info("Initialized DNF API")
            else:
                logger.warning("Neople API key not provided - DNF API will not be available")
                self._api_states["dnf"] = False

            self._initialized = True
            logger.info("API service initialization complete")

        except Exception as e:
            self._reset_api_states()
            logger.error(f"Failed to initialize API service: {e}")
            raise

    async def _cleanup_apis(self, apis: List[tuple[str, Optional[BaseAPI]]]) -> None:
        """Clean up initialized APIs
        
        Args:
            apis: List of (name, api) tuples to clean up
        """
        cleanup_errors = []
        for api_name, api in apis:
            try:
                if api is None:
                    logger.info(f"Skipping cleanup for {api_name} API (not initialized)")
                    continue
                    
                logger.info(f"Cleaning up {api_name} API...")
                await api.close()
            except Exception as e:
                cleanup_errors.append(f"{api_name}: {str(e)}")
                logger.error(f"Error during {api_name} API cleanup: {e}")
        
        if cleanup_errors:
            logger.error(f"Errors during API cleanup: {', '.join(cleanup_errors)}")

    async def validate_credentials(self) -> bool:
        """Validate all API credentials

        Returns:
            bool: True if all credentials are valid
        """
        try:
            logger.info("Starting API credentials validation...")
            
            apis_to_validate = [
                ("Steam", self._steam_api),
                ("Population", self._population_api),
                ("Exchange", self._exchange_api)
            ]
            
            if self._claude_api:
                apis_to_validate.append(("Claude", self._claude_api))

            for api_name, api in apis_to_validate:
                try:
                    logger.info(f"Validating {api_name} API credentials...")
                    if not await api.validate_credentials():
                        logger.error(f"{api_name} API validation failed")
                        return False
                    logger.info(f"{api_name} API validation successful")
                except Exception as e:
                    logger.error(f"{api_name} API validation failed with error: {str(e)}")
                    return False

            logger.info("All API credentials validated successfully")
            return True

        except Exception as e:
            logger.error(f"Error during API validation: {str(e)}")
            return False

    async def close(self) -> None:
        """Clean up all API clients"""
        try:
            # Create a list of API clients to clean up
            apis_to_cleanup = [
                ("Steam", self._steam_api),
                ("Population", self._population_api),
                ("Exchange", self._exchange_api),
                ("DNF", self._dnf_api),
                ("Claude", self._claude_api)
            ]
            await self._cleanup_apis(apis_to_cleanup)
            
            # Reset API state
            self._reset_api_states()
            self._initialized = False
            
            # Set all API clients to None
            self._steam_api = None
            self._population_api = None
            self._exchange_api = None
            self._dnf_api = None
            self._claude_api = None
            
            logger.info("All API clients cleaned up")
            
        except Exception as e:
            logger.error(f"Error during API service cleanup: {e}")
            # Ensure we reset state even if cleanup fails
            self._reset_api_states()
            self._initialized = False

    async def __aenter__(self) -> 'APIService':
        """Async context manager entry"""
        await self.initialize(self._config)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit"""
        await self.close()

    async def get_exchange_rates(self) -> Dict[str, float]:
        """Get current exchange rates"""
        return await self.exchange.get_exchange_rates()

    def update_notification_channel(self, channel: discord.TextChannel) -> None:
        """Update notification channel for API services
        
        Args:
            channel: New notification channel to use
        """
        if self._claude_api:
            self._claude_api.update_notification_channel(channel)

    def _reset_api_states(self) -> None:
        """Reset all API initialization states"""
        for key in self._api_states:
            self._api_states[key] = False
        self._initialized = False
