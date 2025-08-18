"""
Draft Presenter

Main presenter coordinating between draft views and application service.
Preserves all existing user experience while providing clean separation.
"""

import discord
from discord.ext import commands
from typing import Dict, Set, Optional, List, Any
from ...application.draft_service import DraftApplicationService
from ...application.dto import DraftDTO, JoinResult, VoteResult, PlayerDTO
from ...application.interfaces import IUIPresenter, IPermissionChecker, IThreadService
from ...domain.entities.draft_phase import DraftPhase


class DraftPresenter(IUIPresenter):
    """
    Main presenter for draft UI coordination.
    
    Implements MVP pattern while preserving all existing user interactions.
    """
    
    def __init__(
        self,
        draft_service: Optional[DraftApplicationService],
        permission_checker: IPermissionChecker,
        thread_service: IThreadService,
        bot: commands.Bot
    ):
        self.draft_service = draft_service
        self.permission_checker = permission_checker
        self.thread_service = thread_service
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
        
        # Send or update message with thread support
        try:
            if draft_dto.join_message_id and draft_dto.join_message_id in self.join_message_ids.values():
                # Update existing message
                message = await channel.fetch_message(draft_dto.join_message_id)
                await message.edit(embed=embed, view=view)
            else:
                # For join-based drafts (no thread yet), send to main channel
                # For regular drafts with threads, send to thread
                if draft_dto.thread_id and draft_dto.phase != "waiting":
                    # Send interactive view to thread with fallback to main
                    await self.thread_service.send_to_thread_with_fallback(
                        channel_id=draft_dto.channel_id,
                        thread_id=draft_dto.thread_id,
                        embed=embed,
                        view=view
                    )
                    # Send simplified status to main channel
                    main_embed = discord.Embed(
                        title="🏆 팀 드래프트 대기 중",
                        description=f"스레드에서 드래프트가 진행되고 있어: <#{draft_dto.thread_id}>",
                        color=0x3498db
                    )
                    main_channel = self.bot.get_channel(draft_dto.channel_id)
                    if main_channel:
                        await main_channel.send(embed=main_embed)
                else:
                    # No thread, send to main channel
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
            # Broadcast captain voting to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show captain voting: {e}")
    
    async def show_servant_ban_phase(self, draft_dto: DraftDTO) -> None:
        """Show servant ban phase UI (system bans + captain ban interface)"""
        from ..views.servant_ban import ServantBanView
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Create ban view
        view = ServantBanView(draft_dto, self)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed showing system bans and captain ban progress
        embed = self._create_servant_ban_embed(draft_dto)
        
        try:
            # Broadcast servant ban phase to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show servant ban phase: {e}")
    
    async def show_servant_selection(self, draft_dto: DraftDTO) -> None:
        """Show servant selection UI with category-based interface"""
        from ..views.servant_selection import ServantSelectionView, create_servant_selection_embed
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Create selection view with category support
        view = ServantSelectionView(draft_dto, self)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed using the existing utility function
        embed = create_servant_selection_embed(draft_dto)
        
        try:
            # Broadcast servant selection to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show servant selection: {e}")
    
    async def show_servant_reselection(self, draft_dto: DraftDTO) -> None:
        """Show servant reselection UI for conflicts"""
        from ..views.servant_selection import ServantReselectionView, create_servant_reselection_embed
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Create reselection view
        view = ServantReselectionView(draft_dto, self)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed using the existing utility function
        embed = create_servant_reselection_embed(draft_dto)
        
        try:
            # Broadcast servant reselection to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show servant reselection: {e}")
    
    async def show_captain_ban(self, draft_dto: DraftDTO) -> None:
        """Show captain ban UI with category-based interface"""
        from ..views.captain_ban import CaptainBanView, create_captain_ban_embed
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Create captain ban view with category support
        view = CaptainBanView(draft_dto, self)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed using the utility function
        embed = create_captain_ban_embed(draft_dto)
        
        try:
            # Broadcast captain ban to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show captain ban: {e}")
    
    async def show_team_selection(self, draft_dto: DraftDTO) -> None:
        """Show team selection UI with batch selection support"""
        from ..views.team_selection import TeamSelectionView
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Get available players (not assigned to teams yet)
        available_players = [p for p in draft_dto.players if not p.is_assigned_to_team]
        
        # Create team selection view with batch selection support
        view = TeamSelectionView(self, draft_dto, available_players)
        self.active_views[draft_dto.channel_id] = view
        
        # Create embed showing current teams and selection info
        embed = self._create_team_selection_embed(draft_dto, available_players)
        
        try:
            # Broadcast team selection to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show team selection: {e}")
    
    async def show_game_results(self, draft_dto: DraftDTO) -> None:
        """Show game results UI - matches legacy behavior"""
        from ..views.game_result import GameResultView
        
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Create game result view with finish game button
        view = GameResultView(self, draft_dto.channel_id)
        self.active_views[draft_dto.channel_id] = view
        
        # Create game completion embed showing final teams
        embed = self._create_game_completion_embed(draft_dto)
        
        try:
            # Broadcast final results to both thread and main channel
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed,
                view=view
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show game results: {e}")
    
    def _create_game_completion_embed(self, draft_dto: DraftDTO) -> discord.Embed:
        """Create embed for game completion showing final teams"""
        embed = discord.Embed(
            title="🎉 드래프트 완료!",
            description="팀 구성이 완료되었습니다. 경기를 진행하고 결과를 기록해주세요.",
            color=0x27ae60
        )
        
        # Show final team compositions
        if hasattr(draft_dto, 'teams') and draft_dto.teams:
            for i, team in enumerate(draft_dto.teams, 1):
                if team.players:
                    team_text = []
                    for player in team.players:
                        role = "👑 " if player.user_id == team.captain_id else "⚔️ "
                        servant = f" ({player.selected_servant})" if hasattr(player, 'selected_servant') and player.selected_servant else ""
                        team_text.append(f"{role}{player.username}{servant}")
                    
                    embed.add_field(
                        name=f"팀 {i}",
                        value="\n".join(team_text),
                        inline=True
                    )
        
        embed.add_field(
            name="📝 안내",
            value="경기가 끝나면 '경기 종료 및 결과 기록' 버튼을 눌러 결과를 입력해주세요.\n"
                  "점수 형식: 팀1점수:팀2점수 (예: 12:8)",
            inline=False
        )
        
        return embed
    
    async def update_draft_status(self, draft_dto: DraftDTO) -> None:
        """Update draft status display"""
        if draft_dto.phase == "waiting":
            await self.show_draft_lobby(draft_dto)
        elif draft_dto.phase == "captain_voting":
            await self.update_captain_voting_display(draft_dto)
        elif draft_dto.phase == "servant_selection":
            await self.show_servant_selection(draft_dto)
        elif draft_dto.phase == "servant_ban":
            await self.show_captain_ban(draft_dto)
        elif draft_dto.phase == "servant_reselection":
            await self.show_servant_reselection(draft_dto)
        elif draft_dto.phase == "team_selection":
            await self.show_team_selection(draft_dto)
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
                    # Auto-start captain voting when draft is full
                    await self._auto_start_captain_voting(channel_id)
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
        """Handle captain vote - preserves existing voting logic with comprehensive logging"""
        try:
            # Get current user votes
            if channel_id not in self.captain_votes:
                self.captain_votes[channel_id] = {}
            if voter_id not in self.captain_votes[channel_id]:
                self.captain_votes[channel_id][voter_id] = set()
            
            current_votes = self.captain_votes[channel_id][voter_id]
            
            # Log vote attempt with player names for better tracking
            draft_dto = await self.draft_service.get_draft_status(channel_id)
            voter_name = "Unknown"
            candidate_name = "Unknown"
            if draft_dto:
                voter_player = next((p for p in draft_dto.players if p.user_id == voter_id), None)
                candidate_player = next((p for p in draft_dto.players if p.user_id == candidate_id), None)
                if voter_player:
                    voter_name = voter_player.username
                if candidate_player:
                    candidate_name = candidate_player.username
            
            import logging
            logger = logging.getLogger(__name__)
            
            # Determine vote action (adding or removing)
            is_removing_vote = candidate_id in current_votes
            action = "removing vote for" if is_removing_vote else "voting for"
            
            logger.info(
                f"Captain voting: {voter_name} (ID: {voter_id}) is {action} {candidate_name} (ID: {candidate_id}) "
                f"in channel {channel_id}. Current votes: {len(current_votes)}/2"
            )
            
            # Validate vote through application service
            result = await self.draft_service.vote_for_captain(
                channel_id, voter_id, candidate_id, current_votes
            )
            
            if result.success:
                # Toggle vote - preserves existing toggle behavior
                if candidate_id in current_votes:
                    current_votes.remove(candidate_id)
                    logger.info(
                        f"Captain voting: Successfully removed vote. {voter_name} now has {len(current_votes)}/2 votes"
                    )
                    await interaction.response.send_message(
                        f"투표를 취소했어.", ephemeral=True
                    )
                    # Real-time progress update (legacy behavior)
                    await self._update_captain_voting_progress_real_time(channel_id)
                else:
                    if len(current_votes) >= 2:
                        logger.warning(
                            f"Captain voting: {voter_name} tried to vote for {candidate_name} but already has max votes (2/2)"
                        )
                        await interaction.response.send_message(
                            "최대 2명까지만 투표할 수 있어.", ephemeral=True
                        )
                        return
                    
                    current_votes.add(candidate_id)
                    logger.info(
                        f"Captain voting: Successfully added vote. {voter_name} now has {len(current_votes)}/2 votes: "
                        f"{[next((p.username for p in draft_dto.players if p.user_id == uid), str(uid)) for uid in current_votes]}"
                    )
                    draft_dto = await self.draft_service.get_draft_status(channel_id)
                    if draft_dto:
                        candidate_name = next(
                            (p.username for p in draft_dto.players if p.user_id == candidate_id),
                            "Unknown"
                        )
                        await interaction.response.send_message(
                            f"{candidate_name}에게 투표했어!", ephemeral=True
                        )
                        # Real-time progress update (legacy behavior)
                        await self._update_captain_voting_progress_real_time(channel_id)
                
                # Log current vote state for the channel
                total_votes = sum(len(user_votes) for user_votes in self.captain_votes[channel_id].values())
                max_votes = len(draft_dto.players) * 2 if draft_dto else 0
                logger.info(
                    f"Captain voting: Channel {channel_id} vote progress: {total_votes}/{max_votes} total votes cast"
                )
                
                # Update voting display
                await self.update_captain_voting_progress(channel_id)
                
            else:
                logger.warning(
                    f"Captain voting: Vote failed for {voter_name} -> {candidate_name}. Error: {result.message}"
                )
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
            title="👑 팀장 투표",
            description="팀장으로 원하는 플레이어에게 투표해주세요 (최대 2명)\n"
                       "⏰ 제한 시간: 2분",
            color=0xf39c12
        )
        
        # Show players
        if draft_dto.players:
            player_list = []
            for i, player in enumerate(draft_dto.players, 1):
                player_list.append(f"{i}. {player.username}")
            
            embed.add_field(
                name="투표 대상",
                value="\n".join(player_list),
                inline=False
            )
        
        embed.add_field(
            name="📝 안내",
            value="각 플레이어는 최대 2명의 팀장 후보에게 투표할 수 있습니다.\n"
                  "투표를 취소하려면 같은 버튼을 다시 클릭하세요.",
            inline=False
        )
        
        return embed
    
    def _create_servant_ban_embed(self, draft_dto: DraftDTO) -> discord.Embed:
        """Create servant ban phase embed - shows system bans and captain ban progress"""
        embed = discord.Embed(
            title="🚫 서번트 밴 단계",
            description="시스템 밴과 팀장 밴이 진행됩니다.",
            color=0xe74c3c
        )
        
        # Show system bans if any
        if hasattr(draft_dto, 'system_bans') and draft_dto.system_bans:
            system_ban_text = ", ".join(draft_dto.system_bans)
            embed.add_field(
                name="문 셀 밴",
                value=system_ban_text,
                inline=False
            )
        
        # Show captain ban progress
        if hasattr(draft_dto, 'captains') and draft_dto.captains:
            ban_progress = []
            for i, captain in enumerate(draft_dto.captains):
                captain_player = next((p for p in draft_dto.players if p.user_id == captain.user_id), None)
                if captain_player:
                    status = "✅ 완료" if captain.ban_completed else "⏳ 대기 중"
                    ban_progress.append(f"팀장 {i+1}: {captain_player.username} - {status}")
            
            if ban_progress:
                embed.add_field(
                    name="👑 팀장 밴 진행도",
                    value="\n".join(ban_progress),
                    inline=False
                )
        
        embed.add_field(
            name="📝 안내",
            value="팀장들은 순서대로 1개씩 서번트를 밴할 수 있습니다.",
            inline=False
        )
        
        return embed
    
    def _create_team_selection_embed(self, draft_dto: DraftDTO, available_players: List["PlayerDTO"]) -> discord.Embed:
        """Create team selection embed - shows current teams and selection info"""
        embed = discord.Embed(
            title="🏆 팀 선택 단계",
            description="팀장들이 순서대로 팀원을 선택합니다.\n"
                       "⏰ 제한 시간: 5분",
            color=0x9b59b6
        )
        
        # Show current team compositions
        if hasattr(draft_dto, 'teams') and draft_dto.teams:
            team_info = []
            for i, team in enumerate(draft_dto.teams, 1):
                if team.players:
                    player_names = [p.username for p in team.players]
                    captain_mark = " (팀장)" if team.captain_id else ""
                    team_info.append(f"**팀 {i}**: {', '.join(player_names)}{captain_mark}")
                else:
                    team_info.append(f"**팀 {i}**: 대기 중...")
            
            if team_info:
                embed.add_field(
                    name="현재 팀 구성",
                    value="\n".join(team_info),
                    inline=False
                )
        
        # Show current picking captain and round info
        if hasattr(draft_dto, 'current_picking_captain') and draft_dto.current_picking_captain:
            current_captain = next(
                (p for p in draft_dto.players if p.user_id == draft_dto.current_picking_captain), 
                None
            )
            if current_captain:
                round_num = getattr(draft_dto, 'team_selection_round', 1)
                embed.add_field(
                    name="현재 선택 중",
                    value=f"팀장: {current_captain.username}\n라운드: {round_num}",
                    inline=True
                )
        
        # Show available players
        if available_players:
            player_list = []
            for player in available_players[:10]:  # Limit display
                servant = f" ({player.selected_servant})" if player.selected_servant else ""
                player_list.append(f"• {player.username}{servant}")
            
            if player_list:
                embed.add_field(
                    name="선택 가능한 플레이어",
                    value="\n".join(player_list),
                    inline=False
                )
        
        embed.add_field(
            name="📝 안내",
            value="드롭다운에서 팀원을 선택하고 '선택 확정' 버튼을 눌러주세요.\n"
                  "선택한 팀원은 이름 버튼을 클릭해서 취소할 수 있습니다.",
            inline=False
        )
        
        return embed
    
    async def update_team_selection_display(self, draft_dto: DraftDTO) -> None:
        """Update team selection display after changes"""
        # This would update the existing message with new team compositions
        # For now, we'll just show a new selection interface if needed
        if draft_dto.phase == "team_selection":
            await self.show_team_selection(draft_dto)
    
    async def update_servant_selection_progress(self, draft_dto: DraftDTO) -> None:
        """Update servant selection progress in real-time (legacy behavior)"""
        try:
            # Count completed selections
            completed_count = 0
            total_players = len(draft_dto.players)
            
            # Count players who have completed selection
            for player in draft_dto.players:
                if hasattr(player, 'selected_servant') and player.selected_servant:
                    completed_count += 1
            
            # Create real-time progress embed
            embed = discord.Embed(
                title="🎭 서번트 선택 진행 상황",
                description=f"선택 진행: {completed_count}/{total_players} 플레이어 완료",
                color=0x9b59b6
            )
            
            # Show individual player progress
            progress_lines = []
            for player in draft_dto.players:
                if hasattr(player, 'selected_servant') and player.selected_servant:
                    status = f"✅ {player.selected_servant}"
                else:
                    status = "⏳ 선택 중..."
                progress_lines.append(f"• {player.username}: {status}")
            
            if progress_lines:
                embed.add_field(
                    name="개별 선택 진행도",
                    value="\n".join(progress_lines[:12]),  # Limit to prevent embed overflow
                    inline=False
                )
            
            # Broadcast to thread and main channel
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update servant selection progress: {e}")
    
    async def update_servant_reselection_progress(self, draft_dto: DraftDTO) -> None:
        """Update servant reselection progress in real-time (legacy behavior)"""
        try:
            # Count conflicted players who have reselected
            total_conflicted = 0
            completed_reselections = 0
            
            # Get all conflicted users
            conflicted_users = set()
            for servant, user_ids in draft_dto.conflicted_servants.items():
                conflicted_users.update(user_ids)
            
            total_conflicted = len(conflicted_users)
            
            # Count completed reselections
            for user_id in conflicted_users:
                if user_id in draft_dto.confirmed_servants:
                    completed_reselections += 1
            
            # Create real-time progress embed for reselection
            embed = discord.Embed(
                title="🔄 서번트 재선택 진행 상황",
                description=f"재선택 진행: {completed_reselections}/{total_conflicted} 플레이어 완료",
                color=0xf39c12  # WARNING_COLOR
            )
            
            # Show individual reselection progress
            progress_lines = []
            for user_id in conflicted_users:
                player = next((p for p in draft_dto.players if p.user_id == user_id), None)
                if player:
                    if user_id in draft_dto.confirmed_servants:
                        status = f"✅ {draft_dto.confirmed_servants[user_id]}"
                    else:
                        status = "⏳ 재선택 중..."
                    progress_lines.append(f"• {player.username}: {status}")
            
            if progress_lines:
                embed.add_field(
                    name="개별 재선택 진행도",
                    value="\n".join(progress_lines[:12]),  # Limit to prevent embed overflow
                    inline=False
                )
            
            # Show conflicts that triggered reselection
            if draft_dto.conflicted_servants:
                conflict_text = ""
                for servant, user_ids in draft_dto.conflicted_servants.items():
                    user_names = []
                    for user_id in user_ids:
                        player = next((p for p in draft_dto.players if p.user_id == user_id), None)
                        if player:
                            user_names.append(player.username)
                    if user_names:
                        conflict_text += f"**{servant}**: {', '.join(user_names)}\n"
                
                if conflict_text:
                    embed.add_field(
                        name="충돌 원인",
                        value=conflict_text.strip(),
                        inline=False
                    )
            
            # Broadcast to thread and main channel
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update servant reselection progress: {e}")
    
    async def _update_captain_voting_progress_real_time(self, channel_id: int) -> None:
        """Update captain voting progress in real-time (legacy behavior)"""
        try:
            draft_dto = await self.draft_service.get_draft_status(channel_id)
            if not draft_dto or draft_dto.phase != "captain_voting":
                return
            
            # Get current vote counts
            votes_cast = 0
            total_votes_needed = len(draft_dto.players) * 2  # Each player can vote for 2 captains
            
            if channel_id in self.captain_votes:
                votes_cast = sum(len(user_votes) for user_votes in self.captain_votes[channel_id].values())
            
            # Create real-time progress embed
            embed = discord.Embed(
                title="📊 팀장 투표 진행 상황",
                description=f"투표 진행: {votes_cast}/{total_votes_needed} 투표 완료",
                color=0x3498db
            )
            
            # Show individual player progress
            if channel_id in self.captain_votes:
                progress_lines = []
                for player in draft_dto.players:
                    user_votes = self.captain_votes[channel_id].get(player.user_id, set())
                    vote_count = len(user_votes)
                    status = "✅ 완료" if vote_count == 2 else f"⏳ {vote_count}/2"
                    progress_lines.append(f"• {player.username}: {status}")
                
                if progress_lines:
                    embed.add_field(
                        name="개별 투표 진행도",
                        value="\n".join(progress_lines[:10]),  # Limit to prevent embed overflow
                        inline=False
                    )
            
            # Broadcast to thread and main channel
            await self.thread_service.send_to_thread_and_main(
                channel_id=channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update captain voting progress: {e}")
    
    async def _update_team_selection_progress_real_time(self, channel_id: int) -> None:
        """Update team selection progress in real-time (legacy behavior)"""
        try:
            draft_dto = await self.draft_service.get_draft_status(channel_id)
            if not draft_dto or draft_dto.phase != "team_selection":
                return
            
            # Create real-time progress embed showing current round and pending selections
            current_round = getattr(draft_dto, 'team_selection_round', 1)
            current_captain_id = getattr(draft_dto, 'current_picking_captain', None)
            
            embed = discord.Embed(
                title="🏆 팀 선택 진행 상황",
                description=f"라운드 {current_round} 진행 중",
                color=0x9b59b6
            )
            
            # Show current captain and their pending selections
            if current_captain_id:
                current_captain = next((p for p in draft_dto.players if p.user_id == current_captain_id), None)
                if current_captain:
                    embed.add_field(
                        name="현재 선택 중",
                        value=f"👑 {current_captain.username}",
                        inline=True
                    )
                    
                    # Show pending selections if any
                    if hasattr(draft_dto, 'pending_team_selections') and current_captain_id in draft_dto.pending_team_selections:
                        pending = draft_dto.pending_team_selections[current_captain_id]
                        if pending:
                            pending_names = []
                            for player_id in pending:
                                player = next((p for p in draft_dto.players if p.user_id == player_id), None)
                                if player:
                                    pending_names.append(player.username)
                            
                            if pending_names:
                                embed.add_field(
                                    name="보류 중인 선택",
                                    value=", ".join(pending_names),
                                    inline=True
                                )
            
            # Show current team compositions
            if hasattr(draft_dto, 'teams') and draft_dto.teams:
                team_info = []
                for i, team in enumerate(draft_dto.teams, 1):
                    if team.players:
                        team_size = len(team.players)
                        team_info.append(f"**팀 {i}**: {team_size}명")
                    else:
                        team_info.append(f"**팀 {i}**: 0명")
                
                if team_info:
                    embed.add_field(
                        name="팀 구성 현황",
                        value=" | ".join(team_info),
                        inline=False
                    )
            
            # Broadcast to thread and main channel
            await self.thread_service.send_to_thread_and_main(
                channel_id=channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update team selection progress: {e}")
    
    # ===================
    # Enhanced Progress Methods
    # ===================
    
    async def show_captain_voting_progress(self, draft_dto: DraftDTO, progress_details: Dict[str, Any]) -> None:
        """Show detailed captain voting progress"""
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title="📊 팀장 투표 진행 상황",
            description="현재 투표 진행 상황입니다.",
            color=0x3498db
        )
        
        # Show vote progress
        total_votes_needed = progress_details.get("total_votes_needed", 0)
        votes_cast = progress_details.get("votes_cast", 0)
        
        embed.add_field(
            name="투표 진행도",
            value=f"{votes_cast}/{total_votes_needed} 투표 완료",
            inline=True
        )
        
        try:
            # Broadcast progress to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show captain voting progress: {e}")
    
    async def show_team_selection_progress(self, draft_dto: DraftDTO, round_info: Dict[str, Any]) -> None:
        """Show detailed team selection progress"""
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title="🎯 팀 선택 진행 상황",
            description="현재 팀 선택 진행 상황입니다.",
            color=0x9b59b6
        )
        
        round_num = round_info.get("round", 1)
        current_captain = round_info.get("current_captain")
        
        embed.add_field(
            name="현재 라운드",
            value=f"라운드 {round_num}",
            inline=True
        )
        
        if current_captain:
            captain_player = next((p for p in draft_dto.players if p.user_id == current_captain), None)
            if captain_player:
                embed.add_field(
                    name="현재 선택 중",
                    value=captain_player.username,
                    inline=True
                )
        
        try:
            # Broadcast progress to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show team selection progress: {e}")
    
    async def update_captain_ban_progress(self, draft_dto: DraftDTO) -> None:
        """Update captain ban progress display"""
        try:
            # Show updated captain ban interface
            await self.show_captain_ban_phase(draft_dto)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update captain ban progress: {e}")
    
    async def show_dice_roll_results(self, draft_dto: DraftDTO, dice_results: Dict[int, int]) -> None:
        """Show captain ban order dice roll results"""
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title="🎲 팀장 밴 순서 결정",
            description="주사위 굴리기로 팀장 밴 순서를 결정했어!",
            color=0xe67e22
        )
        
        # Show dice results
        if dice_results:
            dice_text = []
            for captain_id, roll in dice_results.items():
                captain_player = next((p for p in draft_dto.players if p.user_id == captain_id), None)
                if captain_player:
                    dice_text.append(f"**{captain_player.username}**: {roll}")
            
            if dice_text:
                embed.add_field(
                    name="주사위 결과",
                    value="\n".join(dice_text),
                    inline=False
                )
                
                # Show ban order
                sorted_captains = sorted(dice_results.items(), key=lambda x: x[1], reverse=True)
                order_text = []
                for i, (captain_id, roll) in enumerate(sorted_captains, 1):
                    captain_player = next((p for p in draft_dto.players if p.user_id == captain_id), None)
                    if captain_player:
                        order_text.append(f"{i}. {captain_player.username}")
                
                if order_text:
                    embed.add_field(
                        name="밴 순서",
                        value="\n".join(order_text),
                        inline=False
                    )
        
        try:
            # Broadcast dice results to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show dice roll results: {e}")
    
    async def show_system_ban_results(self, draft_dto: DraftDTO, banned_servants: List[str]) -> None:
        """Show system ban results with legacy format"""
        channel = self.bot.get_channel(draft_dto.channel_id)
        if not channel:
            return
        
        # Legacy format: "문 셀 오토마톤" title and "문 셀이 자동으로 서번트를 밴했어." description
        embed = discord.Embed(
            title="문 셀 오토마톤",
            description="문 셀이 자동으로 서번트를 밴했어.",
            color=0xe74c3c
        )
        
        if banned_servants:
            # Group banned servants by tier for legacy format
            s_tier_bans = []
            a_tier_bans = []
            b_tier_bans = []
            
            for servant in banned_servants:
                if servant in draft_dto.servant_tiers.get("S", []):
                    s_tier_bans.append(servant)
                elif servant in draft_dto.servant_tiers.get("A", []):
                    a_tier_bans.append(servant)
                elif servant in draft_dto.servant_tiers.get("B", []):
                    b_tier_bans.append(servant)
            
            # Legacy tier names: "갑" (S-tier), "을" (A-tier), "병" (B-tier)
            ban_text = []
            if s_tier_bans:
                ban_text.append(f"갑: {', '.join(s_tier_bans)}")
            if a_tier_bans:
                ban_text.append(f"을: {', '.join(a_tier_bans)}")
            if b_tier_bans:
                ban_text.append(f"병: {', '.join(b_tier_bans)}")
            
            embed.add_field(
                name="밴된 서번트",
                value="\n".join(ban_text) if ban_text else ", ".join(banned_servants),
                inline=False
            )
        else:
            embed.add_field(
                name="밴된 서번트",
                value="없음",
                inline=False
            )
        
        try:
            # Broadcast system ban results to both thread and main channel (legacy behavior)
            await self.thread_service.send_to_thread_and_main(
                channel_id=draft_dto.channel_id,
                thread_id=draft_dto.thread_id,
                embed=embed
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show system ban results: {e}")
    
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
    
    async def confirm_team_selections(
        self,
        interaction: discord.Interaction,
        captain_id: int,
        channel_id: int,
        selected_player_ids: List[int]
    ) -> bool:
        """Confirm captain's team selections (batch confirmation)"""
        try:
            # Confirm selections through application service
            success = await self.draft_service.confirm_captain_team_selections(
                channel_id, captain_id, selected_player_ids
            )
            
            if success:
                # Update display after successful confirmation
                draft_dto = await self.draft_service.get_draft_status(channel_id)
                if draft_dto:
                    await self.update_team_selection_display(draft_dto)
            
            return success
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to confirm team selections: {e}")
            return False
    
    async def _auto_start_captain_voting(self, channel_id: int) -> None:
        """Auto-start captain voting when draft becomes full - preserves legacy behavior"""
        try:
            # Finalize join process (creates thread and starts captain voting)
            success = await self.draft_service.finalize_join_and_start(channel_id)
            if not success:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to finalize join and start draft for channel {channel_id}")
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to auto-start captain voting: {e}")
    
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
