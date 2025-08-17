"""
New Team Draft Commands

Direct implementation using the new hexagonal architecture.
Replaces the original monolithic team_draft.py completely.
"""

import logging
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from ..team_draft import initialize_integration, DiscordIntegration
from ..commands.base_commands import BaseCommands
from src.utils.decorators import command_handler

logger = logging.getLogger(__name__)


class TeamDraftCommands(BaseCommands):
    """
    New team draft commands using clean architecture.
    
    Completely replaces the original team_draft.py system.
    """
    
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        
        # Initialize new system
        try:
            self.draft_system: DiscordIntegration = initialize_integration(bot)
            logger.info("✅ New team draft system initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize new team draft system: {e}")
            raise  # Don't allow bot to start without working draft system
    
    async def cog_load(self) -> None:
        """Called when cog is loaded"""
        logger.info("🚀 New team draft system loaded and ready!")
    
    async def cog_unload(self) -> None:
        """Called when cog is unloaded"""
        if hasattr(self, 'draft_system') and self.draft_system:
            try:
                await self.draft_system.cleanup_all()
                logger.info("🧹 New team draft system cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up draft system: {e}")
    
    # ===================
    # Draft Creation Commands
    # ===================
    
    @app_commands.command(
        name="페어시작",
        description="뮤 페어시작 12 처럼 입력하면 참가 버튼이 있는 메시지를 보내. 인원이 차면 팀장 투표로 진행돼."
    )
    @app_commands.describe(total_players="총 참가자 수 (4, 6, 10, 12 중 선택)")
    async def draft_start_join_slash(self, interaction: discord.Interaction, total_players: int = 12) -> None:
        """Start join-based draft using new system"""
        try:
            # Validate parameters
            if total_players % 2 != 0 or total_players <= 0:
                await interaction.response.send_message("총 인원수는 2의 배수여야 해", ephemeral=True)
                return
            
            team_size = total_players // 2
            if team_size not in [2, 3, 5, 6]:
                await interaction.response.send_message("팀 크기는 2,3,5,6 중 하나여야 해 (예: 12명, 6v6)", ephemeral=True)
                return
            
            # Create draft using new system
            success = await self.draft_system.create_join_based_draft(
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
                total_players=total_players,
                started_by_user_id=interaction.user.id
            )
            
            if success:
                await interaction.response.send_message(
                    f"🏁 드래프트 참가 모집을 시작했어! ({team_size}v{team_size})", 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "드래프트 시작 중 오류가 발생했어.", 
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Draft start failed: {e}")
            await interaction.response.send_message(
                "드래프트 시작 중 오류가 발생했어.", 
                ephemeral=True
            )
    
    @commands.command(name="페어시작")
    @command_handler()
    async def draft_start_join_chat(self, ctx: commands.Context, total_players: int = 12) -> None:
        """Start join-based draft (prefix command)"""
        try:
            # Validate parameters
            if total_players % 2 != 0 or total_players <= 0:
                await self.send_error(ctx, "총 인원수는 2의 배수여야 해")
                return
            
            team_size = total_players // 2
            if team_size not in [2, 3, 5, 6]:
                await self.send_error(ctx, "팀 크기는 2,3,5,6 중 하나여야 해 (예: 12명, 6v6)")
                return
            
            # Create draft using new system
            success = await self.draft_system.create_join_based_draft(
                channel_id=ctx.channel.id,
                guild_id=ctx.guild.id if ctx.guild else 0,
                total_players=total_players,
                started_by_user_id=ctx.author.id
            )
            
            if success:
                await self.send_success(ctx, f"🏁 드래프트 참가 모집을 시작했어! ({team_size}v{team_size})")
            else:
                await self.send_error(ctx, "드래프트 시작 중 오류가 발생했어.")
                
        except Exception as e:
            logger.error(f"Draft start failed: {e}")
            await self.send_error(ctx, "드래프트 시작 중 오류가 발생했어.")
    
    # ===================
    # Draft Management Commands
    # ===================
    
    @app_commands.command(name="페어취소", description="현재 진행 중인 드래프트를 취소해")
    async def draft_cancel_slash(self, interaction: discord.Interaction) -> None:
        """Cancel draft using new system"""
        try:
            success = await self.draft_system.cancel_draft(
                interaction.channel_id, 
                interaction.user.id
            )
            
            if success:
                await interaction.response.send_message("드래프트가 취소됐어.", ephemeral=True)
            else:
                await interaction.response.send_message("취소할 드래프트가 없거나 권한이 없어.", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Draft cancel failed: {e}")
            await interaction.response.send_message("드래프트 취소 중 오류가 발생했어.", ephemeral=True)
    
    @commands.command(name="페어취소", aliases=["드래프트취소", "페어정리"])
    @command_handler()
    async def draft_cancel_chat(self, ctx: commands.Context) -> None:
        """Cancel draft (prefix command)"""
        try:
            success = await self.draft_system.cancel_draft(ctx.channel.id, ctx.author.id)
            
            if success:
                await self.send_success(ctx, "드래프트가 취소됐어.")
            else:
                await self.send_error(ctx, "취소할 드래프트가 없거나 권한이 없어.")
                
        except Exception as e:
            logger.error(f"Draft cancel failed: {e}")
            await self.send_error(ctx, "드래프트 취소 중 오류가 발생했어.")
    
    @commands.command(name="드래프트상태", aliases=["페어상태"])
    @command_handler()
    async def draft_status(self, ctx: commands.Context) -> None:
        """Show draft status"""
        try:
            status = await self.draft_system.get_draft_status(ctx.channel.id)
            
            if status:
                embed = discord.Embed(
                    title="드래프트 상태",
                    color=0x3498db
                )
                embed.add_field(name="단계", value=status["phase"], inline=True)
                embed.add_field(name="팀 크기", value=f"{status['team_size']}v{status['team_size']}", inline=True)
                embed.add_field(name="플레이어", value=f"{status['player_count']}/{status['team_size']*2}", inline=True)
                embed.add_field(name="시작 가능", value="✅" if status["can_start"] else "❌", inline=True)
                embed.add_field(name="팀 구성 완료", value="✅" if status["is_full"] else "❌", inline=True)
                
                await ctx.send(embed=embed)
            else:
                await self.send_info(ctx, "활성화된 드래프트가 없어.")
                
        except Exception as e:
            logger.error(f"Draft status failed: {e}")
            await self.send_error(ctx, "상태 조회 중 오류가 발생했어.")
    
    # ===================
    # Manual Draft Commands (for advanced users)
    # ===================
    
    @commands.command(name="페어")
    @command_handler()
    async def draft_manual(self, ctx: commands.Context, *, args: str = "") -> None:
        """Manual draft creation with mentioned players"""
        try:
            # Parse mentions and arguments
            mentioned_users = ctx.message.mentions
            
            # If no mentions, show error
            if not mentioned_users:
                await self.send_error(ctx, 
                    "참가자를 멘션해야 해!\n"
                    "사용법: `뮤 페어 @user1 @user2 @user3 @user4` (2v2)\n"
                    "또는 `뮤 페어시작 12` (버튼으로 참가 모집)")
                return
            
            # Parse team_size from args
            team_size = len(mentioned_users) // 2  # default based on mentions
            is_test_mode = False
            
            args_lower = args.lower()
            
            if "team_size:2" in args_lower or "team_size=2" in args_lower:
                team_size = 2
            elif "team_size:3" in args_lower or "team_size=3" in args_lower:
                team_size = 3
            elif "team_size:5" in args_lower or "team_size=5" in args_lower:
                team_size = 5
            elif "team_size:6" in args_lower or "team_size=6" in args_lower:
                team_size = 6
            
            if "test_mode" in args_lower or "테스트" in args_lower:
                is_test_mode = True
            
            # Validate player count
            expected_players = team_size * 2
            if len(mentioned_users) != expected_players:
                await self.send_error(ctx, 
                    f"{team_size}v{team_size} 드래프트에는 {expected_players}명이 필요해! "
                    f"(현재 {len(mentioned_users)}명 멘션됨)")
                return
            
            # Create manual draft with specific players
            player_list = [(user.id, user.display_name) for user in mentioned_users]
            
            success = await self.draft_system.create_manual_draft_with_players(
                channel_id=ctx.channel.id,
                guild_id=ctx.guild.id if ctx.guild else 0,
                players=player_list,
                team_size=team_size,
                started_by_user_id=ctx.author.id,
                is_test_mode=is_test_mode
            )
            
            if success:
                mode_text = " (테스트 모드)" if is_test_mode else ""
                await self.send_success(ctx, f"🏁 수동 드래프트를 시작했어! ({team_size}v{team_size}){mode_text}")
            else:
                await self.send_error(ctx, "드래프트 시작 중 오류가 발생했어.")
                
        except Exception as e:
            logger.error(f"Manual draft failed: {e}")
            await self.send_error(ctx, "드래프트 시작 중 오류가 발생했어.")
    
        # ===================
    # Match Result Commands
    # ===================
    
    @commands.command(name="페어결과", help="최근 드래프트 경기의 결과를 기록합니다")
    @command_handler()
    async def record_match_result(self, ctx: commands.Context, winner: int, *, score: str = "") -> None:
        """Record match result for completed draft"""
        try:
            # Validate winner
            if winner not in (1, 2):
                await self.send_error(ctx, "승리 팀은 1 또는 2여야 해")
                return
            
            # Record result through draft system
            success = await self.draft_system.record_match_result(
                channel_id=ctx.channel.id,
                winner=winner,
                score=score or None
            )
            
            if success:
                result_text = f"팀 {winner} 승리"
                if score:
                    result_text += f" ({score})"
                await self.send_success(ctx, f"경기 결과가 기록됐어: {result_text}")
            else:
                await self.send_error(ctx, "결과를 기록할 수 없어. 완료된 드래프트가 있는지 확인해줘.")
                
        except Exception as e:
            logger.error(f"Match result recording failed: {e}")
            await self.send_error(ctx, "결과 기록 중 문제가 발생했어")
    
    @app_commands.command(name="페어결과", description="드래프트 경기 결과를 기록해")
    async def record_match_result_slash(self, interaction: discord.Interaction, winner: int, score: str = "") -> None:
        """Record match result (slash command)"""
        try:
            # Validate winner
            if winner not in (1, 2):
                await interaction.response.send_message("승리 팀은 1 또는 2여야 해", ephemeral=True)
                return
            
            # Record result through draft system
            success = await self.draft_system.record_match_result(
                channel_id=interaction.channel_id or 0,
                winner=winner,
                score=score or None
            )
            
            if success:
                result_text = f"팀 {winner} 승리"
                if score:
                    result_text += f" ({score})"
                await interaction.response.send_message(f"경기 결과가 기록됐어: {result_text}")
            else:
                await interaction.response.send_message("결과를 기록할 수 없어. 완료된 드래프트가 있는지 확인해줘.", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Match result recording failed: {e}")
            await interaction.response.send_message("결과 기록 중 문제가 발생했어", ephemeral=True)
    
    # ===================
    # Admin Commands  
    # ===================
    
    @commands.command(name="페어정리", help="진행 중인 드래프트를 강제로 정리해 (관리자용)", hidden=True)
    @commands.has_permissions(manage_messages=True)
    @command_handler()
    async def draft_force_cleanup(self, ctx: commands.Context, channel_id: str = None) -> None:
        """Force cleanup a draft (admin only)"""
        try:
            # Determine target channel
            if channel_id:
                try:
                    target_channel_id = int(channel_id)
                except ValueError:
                    await self.send_error(ctx, "올바른 채널 ID를 입력해줘.")
                    return
            else:
                target_channel_id = ctx.channel.id
            
            # Force cleanup through draft system
            success = await self.draft_system.force_cleanup_draft(
                channel_id=target_channel_id,
                admin_user_id=ctx.author.id
            )
            
            if success:
                await self.send_success(ctx, f"채널 {target_channel_id}의 드래프트를 강제로 정리했어.")
            else:
                await self.send_error(ctx, f"채널 {target_channel_id}에 정리할 드래프트가 없어.")
                
        except Exception as e:
            logger.error(f"Force cleanup failed: {e}")
            await self.send_error(ctx, "드래프트 정리 중 문제가 발생했어")
    
    @app_commands.command(name="페어정리", description="진행 중인 드래프트를 강제로 정리해 (관리자용)")
    @app_commands.default_permissions(manage_messages=True)
    async def draft_force_cleanup_slash(self, interaction: discord.Interaction, channel_id: str = None) -> None:
        """Force cleanup a draft (admin only)"""
        try:
            # Determine target channel
            if channel_id:
                try:
                    target_channel_id = int(channel_id)
                except ValueError:
                    await interaction.response.send_message("올바른 채널 ID를 입력해줘.", ephemeral=True)
                    return
            else:
                target_channel_id = interaction.channel_id or 0
            
            # Force cleanup through draft system
            success = await self.draft_system.force_cleanup_draft(
                channel_id=target_channel_id,
                admin_user_id=interaction.user.id
            )
            
            if success:
                await interaction.response.send_message(f"채널 {target_channel_id}의 드래프트를 강제로 정리했어.")
            else:
                await interaction.response.send_message(f"채널 {target_channel_id}에 정리할 드래프트가 없어.", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Force cleanup failed: {e}")
            await interaction.response.send_message("드래프트 정리 중 문제가 발생했어", ephemeral=True)

    # ===================
    # System Information Commands
    # =================== 
    
    @commands.command(name="시스템정보")
    async def system_info(self, ctx: commands.Context) -> None:
        """Show new system information"""
        try:
            stats = self.draft_system.get_stats()
            
            embed = discord.Embed(
                title="🆕 새 드래프트 시스템",
                description="헥사고날 아키텍처 기반 드래프트 시스템",
                color=0x2ecc71
            )
            
            embed.add_field(
                name="활성 드래프트", 
                value=f"{stats['active_drafts']}개", 
                inline=True
            )
            
            embed.add_field(
                name="시스템 상태", 
                value=stats['system_status'], 
                inline=True
            )
            
            embed.add_field(
                name="아키텍처", 
                value="Hexagonal + MVP", 
                inline=True
            )
            
            # Feature status
            features = stats.get('feature_flags', {})
            feature_text = ""
            for feature, enabled in features.items():
                status = "✅" if enabled else "➖"
                feature_text += f"{status} {feature}\n"
            
            if feature_text:
                embed.add_field(
                    name="기능 상태", 
                    value=feature_text, 
                    inline=False
                )
            
            embed.add_field(
                name="주요 개선점",
                value="• 테스트 가능한 코드\n• 명확한 책임 분리\n• 빠른 기능 개발\n• 안정적인 배포",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"System info failed: {e}")
            await self.send_error(ctx, "시스템 정보 조회 중 오류가 발생했어.")
    
    # ===================
    # Feature Flag Commands (Owner Only)
    # ===================
    
    @commands.command(name="기능설정")
    @commands.is_owner()
    async def feature_management(self, ctx: commands.Context, action: str = "", feature: str = "") -> None:
        """Manage system features (owner only)"""
        try:
            if not action:
                # Show current feature status
                status = self.draft_system.get_feature_status()
                
                embed = discord.Embed(
                    title="🎛️ 기능 관리",
                    description="새 시스템 기능 상태",
                    color=0x3498db
                )
                
                for feature_name, enabled in status.items():
                    status_emoji = "✅" if enabled else "❌"
                    embed.add_field(
                        name=f"{status_emoji} {feature_name}",
                        value="활성화됨" if enabled else "비활성화됨",
                        inline=True
                    )
                
                embed.add_field(
                    name="사용법",
                    value="`기능설정 enable [기능명]` - 활성화\n`기능설정 disable [기능명]` - 비활성화",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                return
            
            if action.lower() in ["enable", "활성화"]:
                if not feature:
                    await self.send_error(ctx, "활성화할 기능명을 입력해줘.")
                    return
                
                success = self.draft_system.enable_feature(feature.upper())
                if success:
                    await self.send_success(ctx, f"✅ {feature} 기능을 활성화했어.")
                else:
                    await self.send_error(ctx, f"❌ {feature} 기능을 찾을 수 없어.")
            
            elif action.lower() in ["disable", "비활성화"]:
                if not feature:
                    await self.send_error(ctx, "비활성화할 기능명을 입력해줘.")
                    return
                
                success = self.draft_system.disable_feature(feature.upper())
                if success:
                    await self.send_success(ctx, f"❌ {feature} 기능을 비활성화했어.")
                else:
                    await self.send_error(ctx, f"❌ {feature} 기능을 찾을 수 없어.")
            
            else:
                await self.send_error(ctx, "사용법: `기능설정 [enable/disable] [기능명]`")
                
        except Exception as e:
            logger.error(f"Feature management failed: {e}")
            await self.send_error(ctx, "기능 설정 중 오류가 발생했어.")
    
    # ===================
    # Legacy Compatibility (Empty Stubs)
    # ===================
    
    def _register_view(self, channel_id: int, view) -> None:
        """Legacy compatibility - no longer needed"""
        pass
    
    async def _cleanup_views(self, channel_id: int) -> None:
        """Legacy cleanup - handled by new system"""
        try:
            await self.draft_system.cleanup_channel(channel_id)
        except Exception as e:
            logger.debug(f"Cleanup failed: {e}")
    
    @property
    def active_drafts(self) -> dict:
        """Legacy compatibility - return empty dict"""
        return {}
    
    # ===================
    # Health Check
    # ===================
    
    async def health_check(self) -> bool:
        """Check if the draft system is healthy"""
        try:
            stats = self.draft_system.get_stats()
            return stats.get('system_status') == 'operational'
        except Exception:
            return False
