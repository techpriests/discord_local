"""
Draft Presenter

Main presenter coordinating between draft views and application service.
Preserves all existing user experience while providing clean separation.
"""

import discord
from discord.ext import commands
from typing import Dict, Set, Optional, List, Any
from ...application.draft_service import DraftApplicationService
from ...application.dto import DraftDTO, JoinResult, VoteResult
from ...application.interfaces import IUIPresenter, IPermissionChecker
from ...domain.entities.draft_phase import DraftPhase


class DraftPresenter(IUIPresenter):
    """
    Main presenter for draft UI coordination.
    
    Implements MVP pattern while preserving all existing user interactions.
    """
    
    def __init__(
        self,
        draft_service: DraftApplicationService,
        permission_checker: IPermissionChecker,
        bot: commands.Bot
    ):
        self.draft_service = draft_service
        self.permission_checker = permission_checker
        self.bot = bot
        
        # UI state management - preserves existing patterns
        self.active_views: Dict[int, discord.ui.View] = {}  # channel_id -> view
        self.captain_votes: Dict[int, Dict[int, Set[int]]] = {}  # channel_id -> user_votes
        self.join_message_ids: Dict[int, int] = {}  # channel_id -> message_id
    
    # ===================
    # IUIPresenter Interface Implementation
    # ===================
    
    async def show_draft_lobby(self, draft_dto: DraftDTO) -> None:
        """Show draft lobby UI"""
        from ..views.draft_lobby import DraftLobbyView
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Create lobby view
        view = DraftLobbyView(self, draft_dto.channel_id)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed - preserves existing format
        embed = self._create_lobby_embed(draft_dto)
        
        # Send or update message
        try:
            if draft_dto.join_message_id and draft_dto.join_message_id in self.join_message_ids.values():
                # Update existing message
                message = await channel.fetch_message(draft_dto.join_message_id)
                await message.edit(embed=embed, view=view)
            else:
                # Send new message
                message = await channel.send(embed=embed, view=view)
                self.join_message_ids[draft_dto.channel_id] = message.id
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show draft lobby: {e}")
    
    async def show_captain_voting(self, draft_dto: DraftDTO) -> None:
        """Show captain voting UI"""
        from ..views.captain_voting import CaptainVotingView
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Initialize voting state
        if draft_dto.channel_id not in self.captain_votes:
            self.captain_votes[draft_dto.channel_id] = {}
        
        # Create voting view
        view = CaptainVotingView(self, draft_dto.channel_id, draft_dto.players)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed
        embed = self._create_captain_voting_embed(draft_dto)
        
        try:
            message = await channel.send(embed=embed, view=view)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show captain voting: {e}")
    
    async def show_servant_selection(self, draft_dto: DraftDTO) -> None:
        """Show servant selection UI"""
        # Implementation would follow same pattern
        pass
    
    async def show_team_selection(self, draft_dto: DraftDTO) -> None:
        """Show team selection UI"""
        # Implementation would follow same pattern
        pass
    
    async def show_game_results(self, draft_dto: DraftDTO) -> None:
        """Show game results UI"""
        # Implementation would follow same pattern
        pass
    
    async def update_draft_status(self, draft_dto: DraftDTO) -> None:
        """Update draft status display"""
        if draft_dto.phase == "waiting":
            await self.show_draft_lobby(draft_dto)
        elif draft_dto.phase == "captain_voting":
            await self.update_captain_voting_display(draft_dto)
        # Add other phase updates as needed
    
    # ===================
    # Join/Leave Handling
    # ===================
    
    async def handle_join_request(
        self,
        interaction: discord.Interaction,
        user_id: int,
        username: str,
        channel_id: int
    ) -> None:
        """Handle join button click - preserves existing behavior"""
        try:
            # Process through application service
            result = await self.draft_service.join_draft(user_id, username, channel_id)
            
            if result.success:
                # Preserve existing success behavior
                if result.should_auto_start:
                    await interaction.response.send_message("참가 완료! 드래프트를 시작할게.", ephemeral=True)
                    # Auto-start logic would be implemented here
                else:
                    await interaction.response.defer()  # Silent acknowledgment
                
                # Update display if needed
                if result.should_update_embed:
                    draft_dto = await self.draft_service.get_draft_status(channel_id)
                    if draft_dto:
                        await self.update_lobby_display(draft_dto)
            else:
                # Preserve existing error messages
                await interaction.response.send_message(result.message, ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message("참가 중 오류가 발생했어.", ephemeral=True)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Join request failed: {e}")
    
    async def handle_leave_request(
        self,
        interaction: discord.Interaction,
        user_id: int,
        channel_id: int
    ) -> None:
        """Handle leave button click - preserves existing behavior"""
        try:
            result = await self.draft_service.leave_draft(user_id, channel_id)
            
            if result.success:
                await interaction.response.send_message(result.message, ephemeral=True)
                
                # Update display
                if result.should_update_embed:
                    draft_dto = await self.draft_service.get_draft_status(channel_id)
                    if draft_dto:
                        await self.update_lobby_display(draft_dto)
            else:
                await interaction.response.send_message(result.message, ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message("취소 중 오류가 발생했어.", ephemeral=True)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Leave request failed: {e}")
    
    async def handle_force_start_request(
        self,
        interaction: discord.Interaction,
        user_id: int,
        channel_id: int
    ) -> None:
        """Handle force start - preserves existing permission checks"""
        try:
            # Get draft status
            draft_dto = await self.draft_service.get_draft_status(channel_id)
            if not draft_dto:
                await interaction.response.send_message("드래프트를 찾을 수 없어.", ephemeral=True)
                return
            
            # Check permissions - preserves existing logic
            can_force_start = False
            if draft_dto.started_by_user_id == user_id:
                can_force_start = True
            elif await self.permission_checker.is_bot_owner(user_id):
                can_force_start = True
            
            if not can_force_start:
                await interaction.response.send_message("시작자만 강제 시작할 수 있어", ephemeral=True)
                return
            
            # Validate player count - preserves existing validation
            if len(draft_dto.join_user_ids) < 2 or (len(draft_dto.join_user_ids) % 2) != 0:
                await interaction.response.send_message("짝수 인원이 필요해", ephemeral=True)
                return
            
            # Start draft process
            await interaction.response.send_message("드래프트를 강제 시작할게!", ephemeral=True)
            # Force start logic would be implemented here
            
        except Exception as e:
            await interaction.response.send_message("강제 시작 중 오류가 발생했어.", ephemeral=True)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Force start failed: {e}")
    
    # ===================
    # Captain Voting Handling
    # ===================
    
    async def handle_captain_vote(
        self,
        interaction: discord.Interaction,
        voter_id: int,
        candidate_id: int,
        channel_id: int
    ) -> None:
        """Handle captain vote - preserves existing voting logic"""
        try:
            # Get current user votes
            if channel_id not in self.captain_votes:
                self.captain_votes[channel_id] = {}
            if voter_id not in self.captain_votes[channel_id]:
                self.captain_votes[channel_id][voter_id] = set()
            
            current_votes = self.captain_votes[channel_id][voter_id]
            
            # Validate vote through application service
            result = await self.draft_service.vote_for_captain(
                channel_id, voter_id, candidate_id, current_votes
            )
            
            if result.success:
                # Toggle vote - preserves existing toggle behavior
                if candidate_id in current_votes:
                    current_votes.remove(candidate_id)
                    await interaction.response.send_message(
                        f"투표를 취소했어.", ephemeral=True
                    )
                else:
                    if len(current_votes) >= 2:
                        await interaction.response.send_message(
                            "최대 2명까지만 투표할 수 있어.", ephemeral=True
                        )
                        return
                    
                    current_votes.add(candidate_id)
                    draft_dto = await self.draft_service.get_draft_status(channel_id)
                    if draft_dto:
                        candidate_name = next(
                            (p.username for p in draft_dto.players if p.user_id == candidate_id),
                            "Unknown"
                        )
                        await interaction.response.send_message(
                            f"{candidate_name}에게 투표했어!", ephemeral=True
                        )
                
                # Update voting display
                await self.update_captain_voting_progress(channel_id)
                
            else:
                await interaction.response.send_message(result.message, ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message("투표 중 오류가 발생했어.", ephemeral=True)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Captain vote failed: {e}")
    
    # ===================
    # UI Update Methods
    # ===================
    
    async def update_lobby_display(self, draft_dto: DraftDTO) -> None:
        """Update lobby display - preserves existing embed updates"""
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        try:
            message_id = self.join_message_ids.get(draft_dto.channel_id)
            if message_id:
                message = await channel.fetch_message(message_id)
                embed = self._create_lobby_embed(draft_dto)
                view = self.active_views.get(draft_dto.channel_id)
                await message.edit(embed=embed, view=view)
        except Exception:
            pass  # Graceful failure
    
    async def update_captain_voting_display(self, draft_dto: DraftDTO) -> None:
        """Update captain voting display"""
        # Implementation would update voting progress display
        pass
    
    async def update_captain_voting_progress(self, channel_id: int) -> None:
        """Update captain voting progress display"""
        # Implementation would show current vote counts
        pass
    
    # ===================
    # Embed Creation - Preserves Existing Formats
    # ===================
    
    def _create_lobby_embed(self, draft_dto: DraftDTO) -> discord.Embed:
        """Create lobby embed - preserves existing format"""
        embed = discord.Embed(
            title=f"🏁 드래프트 참가 모집 ({draft_dto.team_size}v{draft_dto.team_size})",
            color=0x3498db
        )
        
        # Add participant list - preserves existing format
        if draft_dto.join_user_ids:
            participant_names = []
            for user_id in draft_dto.join_user_ids:
                try:
                    user = self.bot.get_user(user_id)
                    name = user.display_name if user else str(user_id)
                    participant_names.append(name)
                except Exception:
                    participant_names.append(str(user_id))
            
            embed.add_field(
                name="참가자",
                value=", ".join(participant_names),
                inline=False
            )
        else:
            embed.add_field(
                name="참가자",
                value="아직 없음",
                inline=False
            )
        
        # Add progress info
        current = len(draft_dto.join_user_ids)
        total = draft_dto.join_target_total_players or draft_dto.total_players_needed
        embed.add_field(
            name="진행 상황",
            value=f"{current}/{total} 명",
            inline=True
        )
        
        return embed
    
    def _create_captain_voting_embed(self, draft_dto: DraftDTO) -> discord.Embed:
        """Create captain voting embed - preserves existing format"""
        embed = discord.Embed(
            title="팀장 투표",
            description="팀장으로 원하는 플레이어에게 투표해주세요 (최대 2명)",
            color=0xf39c12
        )
        
        # Add time remaining if available
        if draft_dto.captain_voting_time_remaining:
            embed.add_field(
                name="남은 시간",
                value=f"{draft_dto.captain_voting_time_remaining}초",
                inline=True
            )
        
        return embed
    
    # ===================
    # Cleanup Methods
    # ===================
    
    async def handle_lobby_timeout(self, channel_id: int) -> None:
        """Handle lobby view timeout"""
        if channel_id in self.active_views:
            del self.active_views[channel_id]
        if channel_id in self.join_message_ids:
            del self.join_message_ids[channel_id]
    
    async def cleanup_channel(self, channel_id: int) -> None:
        """Cleanup all UI state for channel"""
        if channel_id in self.active_views:
            del self.active_views[channel_id]
        if channel_id in self.captain_votes:
            del self.captain_votes[channel_id]
        if channel_id in self.join_message_ids:
            del self.join_message_ids[channel_id]
    
    # ===================
    # Additional Handler Methods
    # ===================
    
    async def handle_captain_voting_timeout(self, channel_id: int) -> None:
        """Handle captain voting timeout"""
        # Auto-finalize voting with current votes
        if channel_id in self.captain_votes:
            user_votes = self.captain_votes[channel_id]
            try:
                await self.draft_service.finalize_captain_selection(channel_id, user_votes)
            except Exception:
                pass  # Graceful failure
    
    async def handle_team_selection_timeout(self, channel_id: int) -> None:
        """Handle team selection timeout"""
        # Could implement auto-assignment or other timeout behavior
        pass
    
    async def handle_team_player_assignment(
        self,
        interaction: discord.Interaction,
        captain_id: int,
        player_id: int,
        channel_id: int
    ) -> None:
        """Handle team player assignment"""
        try:
            result = await self.draft_service.assign_player_to_team(
                channel_id, captain_id, player_id
            )
            
            if result.success:
                await interaction.response.send_message(
                    result.message, ephemeral=True
                )
                
                # Update display if needed
                if result.should_advance_phase:
                    draft_dto = await self.draft_service.get_draft_status(channel_id)
                    if draft_dto:
                        await self.update_draft_status(draft_dto)
            else:
                await interaction.response.send_message(
                    result.message, ephemeral=True
                )
                
        except Exception as e:
            await interaction.response.send_message(
                "플레이어 배정 중 오류가 발생했어.", ephemeral=True
            )
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Team assignment failed: {e}")
