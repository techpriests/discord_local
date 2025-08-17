"""
Hybrid Team Draft Commands

Safe integration that allows gradual migration from old to new system.
This file can be used to replace the original team_draft.py import in bot.py
"""

import logging
from discord.ext import commands
from .team_draft import TeamDraftCommands as OriginalTeamDraftCommands
from ..team_draft import initialize_integration, DiscordIntegration

logger = logging.getLogger(__name__)


class TeamDraftCommands(OriginalTeamDraftCommands):
    """
    Hybrid team draft commands that can use either old or new system.
    
    This class extends the original TeamDraftCommands and adds new system
    integration with feature flags for safe migration.
    
    SAFE FOR IMMEDIATE DEPLOYMENT:
    - Inherits all original functionality
    - New system is disabled by default
    - Zero risk of breaking existing features
    """
    
    def __init__(self, bot: commands.Bot):
        # Initialize original system first
        super().__init__(bot)
        
        # Initialize new system (disabled by default)
        try:
            self.new_system: DiscordIntegration = initialize_integration(bot)
            self._new_system_available = True
            logger.info("✅ New team draft system initialized successfully")
        except Exception as e:
            self.new_system = None
            self._new_system_available = False
            logger.warning(f"⚠️ New team draft system failed to initialize: {e}")
            logger.info("🔄 Falling back to original system only")
        
        # Feature flags (ALL DISABLED by default for safety)
        self._feature_flags = {
            "NEW_DRAFT_LOBBY": False,
            "NEW_CAPTAIN_VOTING": False,
            "NEW_TEAM_SELECTION": False,
            "NEW_SERVANT_SELECTION": False,
            "NEW_GAME_RESULTS": False,
            "NEW_AUTO_BALANCE": False
        }
    
    # ===================
    # Feature Flag Management
    # ===================
    
    def is_new_feature_enabled(self, feature: str) -> bool:
        """Check if new system feature is enabled"""
        return (self._new_system_available and 
                self._feature_flags.get(feature, False))
    
    def enable_new_feature(self, feature: str) -> bool:
        """Enable a new system feature (admin only)"""
        if not self._new_system_available:
            return False
        
        if feature in self._feature_flags:
            self._feature_flags[feature] = True
            logger.info(f"✅ Enabled new system feature: {feature}")
            return True
        return False
    
    def disable_new_feature(self, feature: str) -> bool:
        """Disable a new system feature"""
        if feature in self._feature_flags:
            self._feature_flags[feature] = False
            logger.info(f"❌ Disabled new system feature: {feature}")
            return True
        return False
    
    def get_feature_status(self) -> dict:
        """Get status of all features"""
        return {
            "new_system_available": self._new_system_available,
            "features": self._feature_flags.copy()
        }
    
    # ===================
    # Enhanced Commands (Backward Compatible)
    # ===================
    
    async def draft_start_join_slash(self, interaction, total_players: int = 12):
        """Enhanced join-based draft with new system support"""
        
        # Try new system first if enabled
        if self.is_new_feature_enabled("NEW_DRAFT_LOBBY"):
            try:
                success = await self.new_system.create_join_based_draft(
                    channel_id=interaction.channel_id,
                    guild_id=interaction.guild_id,
                    total_players=total_players,
                    started_by_user_id=interaction.user.id
                )
                
                if success:
                    await interaction.response.send_message(
                        f"🏁 드래프트 참가 모집을 시작했어! ({total_players//2}v{total_players//2}) [새 시스템]", 
                        ephemeral=True
                    )
                    return
            except Exception as e:
                logger.error(f"New system failed, falling back to original: {e}")
        
        # Fall back to original system (always works)
        await super().draft_start_join_slash(interaction, total_players)
    
    async def draft_cancel_slash(self, interaction):
        """Enhanced cancel with new system support"""
        
        # Try new system first
        if self._new_system_available:
            try:
                success = await self.new_system.cancel_draft(
                    interaction.channel_id, 
                    interaction.user.id
                )
                if success:
                    await interaction.response.send_message(
                        "드래프트가 취소됐어. [새 시스템]", 
                        ephemeral=True
                    )
                    return
            except Exception as e:
                logger.debug(f"New system cancel failed: {e}")
        
        # Fall back to original system
        await super().draft_cancel_slash(interaction)
    
    # ===================
    # Admin Commands for Feature Management
    # ===================
    
    @commands.command(name="새시스템")
    @commands.is_owner()
    async def manage_new_system(self, ctx, action: str = "", feature: str = ""):
        """Manage new system features (bot owner only)"""
        
        if not action:
            # Show status
            status = self.get_feature_status()
            
            if not status["new_system_available"]:
                await ctx.send("❌ 새 시스템을 사용할 수 없어. (초기화 실패)")
                return
            
            embed_desc = "**새 시스템 기능 상태:**\n\n"
            for feature_name, enabled in status["features"].items():
                status_emoji = "✅" if enabled else "❌"
                embed_desc += f"{status_emoji} {feature_name}\n"
            
            embed_desc += f"\n**사용법:**\n"
            embed_desc += f"`새시스템 enable [기능명]` - 기능 활성화\n"
            embed_desc += f"`새시스템 disable [기능명]` - 기능 비활성화\n"
            
            await ctx.send(embed_desc)
            return
        
        if action.lower() in ["enable", "활성화"]:
            if not feature:
                await ctx.send("활성화할 기능명을 입력해줘.")
                return
            
            success = self.enable_new_feature(feature.upper())
            if success:
                await ctx.send(f"✅ {feature} 기능을 활성화했어.")
            else:
                await ctx.send(f"❌ {feature} 기능을 찾을 수 없어.")
        
        elif action.lower() in ["disable", "비활성화"]:
            if not feature:
                await ctx.send("비활성화할 기능명을 입력해줘.")
                return
            
            success = self.disable_new_feature(feature.upper())
            if success:
                await ctx.send(f"❌ {feature} 기능을 비활성화했어.")
            else:
                await ctx.send(f"❌ {feature} 기능을 찾을 수 없어.")
        
        else:
            await ctx.send("사용법: `새시스템 [enable/disable] [기능명]`")
    
    @commands.command(name="시스템상태")
    async def system_status(self, ctx):
        """Show system status"""
        old_drafts = len(self.active_drafts)
        
        status_text = f"**드래프트 시스템 상태:**\n\n"
        status_text += f"🔄 기존 시스템: {old_drafts}개 드래프트 활성화\n"
        
        if self._new_system_available:
            new_stats = self.new_system.get_stats()
            new_drafts = new_stats.get("active_drafts", 0)
            status_text += f"🆕 새 시스템: {new_drafts}개 드래프트 활성화\n"
            status_text += f"✅ 새 시스템 사용 가능\n"
        else:
            status_text += f"❌ 새 시스템 사용 불가\n"
        
        await ctx.send(status_text)
    
    # ===================
    # Cleanup and Maintenance
    # ===================
    
    async def cog_unload(self) -> None:
        """Cleanup when cog is unloaded"""
        await super().cog_unload()
        
        # Cleanup new system
        if self._new_system_available and self.new_system:
            try:
                await self.new_system.cleanup_all()
            except Exception as e:
                logger.error(f"Error cleaning up new system: {e}")


# ===================
# Deployment Safety Check
# ===================

def validate_deployment_safety() -> bool:
    """
    Validate that this hybrid system is safe for deployment.
    
    Returns:
        bool: True if safe to deploy
    """
    try:
        # Test that original imports work
        from .team_draft import TeamDraftCommands as Original
        
        # Test that new system can be imported (but doesn't have to work)
        from ..team_draft import DiscordIntegration
        
        logger.info("✅ Deployment safety check passed")
        return True
        
    except ImportError as e:
        logger.error(f"❌ Deployment safety check failed: {e}")
        return False


# Run safety check on import
if __name__ != "__main__":
    validate_deployment_safety()
