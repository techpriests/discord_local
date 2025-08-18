"""
Discord Integration Layer

Main entry point for integrating the new team draft system with Discord commands.
Provides feature flag support for gradual migration.
"""

import discord
from discord.ext import commands
from typing import Optional
from ..infrastructure.container import DraftContainer, initialize_container
from .presenters.draft_presenter import DraftPresenter


class FeatureFlags:
    """Feature flags for the new system - ALL ENABLED since old system is not working"""
    NEW_DRAFT_LOBBY = True
    NEW_CAPTAIN_VOTING = True  
    NEW_TEAM_SELECTION = True
    NEW_SERVANT_SELECTION = True
    NEW_GAME_RESULTS = True
    NEW_AUTO_BALANCE = False  # Keep disabled - still under development


class DiscordIntegration:
    """
    Main integration class for the new team draft system.
    
    Provides clean interface for Discord commands while maintaining
    backward compatibility during migration.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.container = initialize_container(bot)
        self.presenter = None
        self._setup_presenter()
    
    def _setup_presenter(self):
        """Setup the main draft presenter"""
        # Create presenter first (without draft service to avoid circular dependency)
        self.presenter = DraftPresenter(
            draft_service=None,  # Will be set after container registration
            permission_checker=self.container.get_permission_checker(),
            thread_service=self.container.get_thread_service(),
            bot=self.bot
        )
        
        # Register presenter with container first
        self.container.set_ui_presenter(self.presenter)
        
        # Now set the draft service after presenter is registered
        self.presenter.draft_service = self.container.get_draft_service()
    
    # ===================
    # Draft Lifecycle Methods
    # ===================
    
    async def create_join_based_draft(
        self,
        channel_id: int,
        guild_id: int,
        total_players: int = 12,
        started_by_user_id: Optional[int] = None
    ) -> bool:
        """
        Create a join-based draft.
        
        Returns:
            bool: True if created successfully using new system
        """
        if not FeatureFlags.NEW_DRAFT_LOBBY:
            return False  # Fall back to old system
        
        try:
            draft_service = self.container.get_draft_service()
            await draft_service.start_join_draft(
                channel_id=channel_id,
                guild_id=guild_id,
                total_players=total_players,
                started_by_user_id=started_by_user_id
            )
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create join-based draft: {e}")
            return False
    
    async def create_manual_draft(
        self,
        channel_id: int,
        guild_id: int,
        team_size: int = 6,
        started_by_user_id: Optional[int] = None,
        is_test_mode: bool = False
    ) -> bool:
        """
        Create a manual draft.
        
        Returns:
            bool: True if created successfully using new system
        """
        if not FeatureFlags.NEW_DRAFT_LOBBY:
            return False  # Fall back to old system
        
        try:
            draft_service = self.container.get_draft_service()
            await draft_service.create_draft(
                channel_id=channel_id,
                guild_id=guild_id,
                team_size=team_size,
                started_by_user_id=started_by_user_id,
                is_test_mode=is_test_mode
            )
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create manual draft: {e}")
            return False
    
    async def cancel_draft(self, channel_id: int, user_id: int) -> bool:
        """
        Cancel a draft.
        
        Returns:
            bool: True if cancelled successfully using new system
        """
        try:
            draft_service = self.container.get_draft_service()
            return await draft_service.cancel_draft(channel_id, user_id)
        except Exception:
            return False
    
    async def get_draft_status(self, channel_id: int) -> Optional[dict]:
        """
        Get draft status.
        
        Returns:
            dict: Draft status or None if not found
        """
        try:
            draft_service = self.container.get_draft_service()
            draft_dto = await draft_service.get_draft_status(channel_id)
            if draft_dto:
                return {
                    "channel_id": draft_dto.channel_id,
                    "phase": draft_dto.phase,
                    "team_size": draft_dto.team_size,
                    "player_count": draft_dto.current_player_count,
                    "is_full": draft_dto.is_full,
                    "can_start": draft_dto.can_start
                }
            return None
        except Exception:
            return None
    
    async def apply_servant_selection(self, channel_id: int, user_id: int, servant_name: str) -> bool:
        """
        Apply servant selection for a player.
        
        Args:
            channel_id: Channel where draft is happening
            user_id: Player making the selection
            servant_name: Name of the servant being selected
            
        Returns:
            bool: True if selection was applied successfully
        """
        try:
            draft_service = self.container.get_draft_service()
            return await draft_service.apply_servant_selection(channel_id, user_id, servant_name)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to apply servant selection: {e}")
            return False
    
    async def apply_captain_ban(self, channel_id: int, user_id: int, servant_name: str) -> bool:
        """
        Apply captain ban for a player.
        
        Args:
            channel_id: Channel where draft is happening
            user_id: Captain making the ban
            servant_name: Name of the servant being banned
            
        Returns:
            bool: True if ban was applied successfully
        """
        try:
            draft_service = self.container.get_draft_service()
            return await draft_service.apply_captain_ban(channel_id, user_id, servant_name)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to apply captain ban: {e}")
            return False
    
    async def record_match_result(self, channel_id: int, winner: int, score: str = None) -> bool:
        """
        Record match result for a completed draft.
        
        Args:
            channel_id: Channel where draft happened
            winner: Winning team number (1 or 2)
            score: Optional score string
            
        Returns:
            bool: True if result was recorded successfully
        """
        try:
            draft_service = self.container.get_draft_service()
            return await draft_service.record_match_result(channel_id, winner, score)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to record match result: {e}")
            return False
    
    # ===================
    # Feature Flag Methods
    # ===================
    
    def is_new_system_enabled(self, feature: str) -> bool:
        """Check if new system is enabled for a feature"""
        return getattr(FeatureFlags, feature, False)
    
    def enable_feature(self, feature: str) -> bool:
        """Enable a feature flag"""
        if hasattr(FeatureFlags, feature):
            setattr(FeatureFlags, feature, True)
            return True
        return False
    
    def disable_feature(self, feature: str) -> bool:
        """Disable a feature flag"""
        if hasattr(FeatureFlags, feature):
            setattr(FeatureFlags, feature, False)
            return True
        return False
    
    def get_feature_status(self) -> dict:
        """Get status of all feature flags"""
        return {
            "NEW_DRAFT_LOBBY": FeatureFlags.NEW_DRAFT_LOBBY,
            "NEW_CAPTAIN_VOTING": FeatureFlags.NEW_CAPTAIN_VOTING,
            "NEW_TEAM_SELECTION": FeatureFlags.NEW_TEAM_SELECTION,
            "NEW_SERVANT_SELECTION": FeatureFlags.NEW_SERVANT_SELECTION,
            "NEW_GAME_RESULTS": FeatureFlags.NEW_GAME_RESULTS,
            "NEW_AUTO_BALANCE": FeatureFlags.NEW_AUTO_BALANCE
        }
    
    # ===================
    # Integration Helpers
    # ===================
    
    async def should_use_new_system(self, channel_id: int, feature: str) -> bool:
        """
        Determine if new system should be used for a channel/feature.
        
        This can be enhanced with per-guild or per-channel feature flags.
        """
        # For now, use global feature flags
        return self.is_new_system_enabled(feature)
    
    async def migrate_existing_draft(self, channel_id: int) -> bool:
        """
        Migrate an existing draft to new system.
        
        This would be used during gradual migration to move
        in-progress drafts to the new system.
        """
        # Implementation would convert old DraftSession to new Draft entity
        # For now, return False to indicate migration not supported
        return False
    
    # ===================
    # Cleanup and Maintenance
    # ===================
    
    async def cleanup_channel(self, channel_id: int) -> None:
        """Cleanup all draft-related data for a channel"""
        if self.presenter:
            await self.presenter.cleanup_channel(channel_id)
        
        # Cleanup from repository
        draft_service = self.container.get_draft_service()
        await draft_service.cancel_draft(channel_id, 0)  # Force cleanup
    
    async def cleanup_all(self) -> None:
        """Cleanup all resources"""
        self.container.cleanup()
    
    def get_stats(self) -> dict:
        """Get system statistics"""
        repo = self.container.get_draft_repository()
        return {
            "active_drafts": repo.get_draft_count() if hasattr(repo, 'get_draft_count') else 0,
            "feature_flags": self.get_feature_status(),
            "system_status": "operational"
        }


# Global instance for easy access
_integration: Optional[DiscordIntegration] = None


def get_integration() -> Optional[DiscordIntegration]:
    """Get global integration instance"""
    return _integration


def initialize_integration(bot: commands.Bot) -> DiscordIntegration:
    """Initialize global integration instance"""
    global _integration
    _integration = DiscordIntegration(bot)
    return _integration


def cleanup_integration() -> None:
    """Cleanup global integration instance"""
    global _integration
    if _integration:
        import asyncio
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(_integration.cleanup_all())
        _integration = None
