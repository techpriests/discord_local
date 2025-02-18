import asyncio
import logging
from typing import Dict, Optional, List, Tuple
import discord

from src.services.api.exchange import ExchangeAPI
from src.services.api.population import PopulationAPI
from src.services.api.steam import SteamAPI
from src.services.api.gemini import GeminiAPI
from src.services.api.base import BaseAPI

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
        self._config = config
        self._notification_channel = notification_channel
        
        # Initialize API clients as None
        self._steam_api: Optional[SteamAPI] = None
        self._population_api: Optional[PopulationAPI] = None
        self._exchange_api: Optional[ExchangeAPI] = None
        self._gemini_api: Optional[GeminiAPI] = None
        
        # Track initialization state
        self._initialized = False
        self._api_states = {
            "steam": False,
            "population": False,
            "exchange": False,
            "gemini": False
        }
        logger.info("API service instance created")

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
        if not value:
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
    def gemini(self) -> GeminiAPI:
        """Get Gemini API client
        
        Returns:
            GeminiAPI: Gemini API client
            
        Raises:
            ValueError: If Gemini API is not initialized
        """
        self._ensure_initialized()
        if not self._gemini_api:
            raise ValueError("Gemini API is not available - API key not provided")
        return self._gemini_api

    async def initialize(self) -> bool:
        """Initialize all API clients

        Returns:
            bool: True if initialization was successful

        Raises:
            ValueError: If any required API client fails to initialize
        """
        if self._initialized:
            logger.info("API service already initialized")
            return True

        try:
            logger.info("Starting API service initialization...")
            # Reset states at start of initialization
            self._reset_api_states()
            apis_to_init = []
            
            # 1. Create API clients first (without marking as ready)
            try:
                # Steam API (Required)
                logger.info("Creating Steam API client...")
                self._steam_api = SteamAPI(self._get_required_key(self._config, "STEAM_API_KEY"))
                apis_to_init.append(("steam", self._steam_api))
                
                # Population API (Optional)
                logger.info("Creating Population API client...")
                self._population_api = PopulationAPI()
                apis_to_init.append(("population", self._population_api))
                
                # Exchange API (Optional)
                logger.info("Creating Exchange API client...")
                self._exchange_api = ExchangeAPI()
                apis_to_init.append(("exchange", self._exchange_api))
                
                # Optional Gemini API
                if gemini_key := self._config.get("GEMINI_API_KEY"):
                    logger.info("Creating Gemini API client...")
                    self._gemini_api = GeminiAPI(gemini_key)
                    apis_to_init.append(("gemini", self._gemini_api))
                
            except Exception as e:
                logger.error(f"Failed to create API clients: {str(e)}")
                await self._cleanup_apis(apis_to_init)
                self._reset_api_states()
                raise ValueError(f"Failed to create API clients: {str(e)}")
            
            # 2. Initialize and validate required APIs first
            required_apis = [("steam", self._steam_api)]
            for api_name, api in required_apis:
                try:
                    logger.info(f"Initializing required API: {api_name}...")
                    await api.initialize()
                    
                    logger.info(f"Validating {api_name} API credentials...")
                    if not await api.validate_credentials():
                        logger.error(f"Required {api_name} API validation failed")
                        await self._cleanup_apis(apis_to_init)
                        self._reset_api_states()
                        return False
                        
                    # Mark required API as ready
                    self._api_states[api_name] = True
                    logger.info(f"Required {api_name} API initialized and validated successfully")
                    
                except Exception as e:
                    logger.error(f"Failed to initialize required {api_name} API: {str(e)}")
                    await self._cleanup_apis(apis_to_init)
                    self._reset_api_states()
                    raise ValueError(f"Required {api_name} API initialization failed: {str(e)}")
            
            # 3. Initialize and validate optional APIs
            optional_apis = [(n, a) for n, a in apis_to_init if n != "steam"]
            for api_name, api in optional_apis:
                try:
                    logger.info(f"Initializing optional API: {api_name}...")
                    await api.initialize()
                    
                    logger.info(f"Validating {api_name} API credentials...")
                    if await api.validate_credentials():
                        self._api_states[api_name] = True
                        logger.info(f"Optional {api_name} API initialized and validated successfully")
                    else:
                        logger.warning(f"Optional {api_name} API validation failed")
                        
                except Exception as e:
                    logger.warning(f"Optional {api_name} API initialization failed: {str(e)}")
                    # Continue with other optional APIs
            
            self._initialized = True
            logger.info("API service initialization completed")
            return True
            
        except Exception as e:
            logger.error(f"API service initialization failed: {str(e)}", exc_info=True)
            self._initialized = False
            raise ValueError(f"API 초기화에 실패했습니다: {str(e)}")

    async def _cleanup_apis(self, apis: List[tuple[str, BaseAPI]]) -> None:
        """Clean up initialized APIs
        
        Args:
            apis: List of (name, api) tuples to clean up
        """
        cleanup_errors = []
        for api_name, api in apis:
            try:
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
            
            if self._gemini_api:
                apis_to_validate.append(("Gemini", self._gemini_api))

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
        """Cleanup all API clients"""
        apis_to_close = [
            ("Steam", self._steam_api),
            ("Population", self._population_api),
            ("Exchange", self._exchange_api)
        ]
        
        if self._gemini_api:
            apis_to_close.append(("Gemini", self._gemini_api))
            
        await self._cleanup_apis(apis_to_close)
        logger.info("All API clients cleaned up")

    async def __aenter__(self) -> 'APIService':
        """Async context manager entry"""
        await self.initialize()
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
        if self._gemini_api:
            self._gemini_api.update_notification_channel(channel)

    def _reset_api_states(self) -> None:
        """Reset all API initialization states"""
        for key in self._api_states:
            self._api_states[key] = False
        self._initialized = False
