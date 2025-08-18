"""
Draft Application Service

Main application service that coordinates draft operations.
Acts as the facade for all draft-related use cases and coordinates domain services.
"""

import asyncio
import discord
from typing import Dict, List, Optional, Set, Any, Tuple
from ..domain.entities.draft import Draft
from ..domain.entities.draft_phase import DraftPhase
from ..domain.entities.player import Player
from ..domain.services.draft_orchestrator import DraftOrchestrator
from ..domain.services.captain_service import CaptainService
from ..domain.services.team_service import TeamService
from ..domain.services.validation_service import ValidationService
from ..domain.exceptions import (
    DraftError,
    InvalidDraftStateError,
    DraftFullError,
    PlayerAlreadyExistsError,
    PlayerNotFoundError
)
from .interfaces import (
    IDraftRepository,
    IUIPresenter,
    IMatchRecorder,
    IBalanceCalculator,
    INotificationService,
    IThreadService
)
from .dto import (
    DraftDTO,
    JoinResult,
    VoteResult,
    SelectionResult,
    TeamAssignmentResult,
    PhaseTransitionResult,
    ValidationResult
)


class DraftApplicationService:
    """
    Main application service for draft operations.
    
    Coordinates between domain services and infrastructure adapters.
    Preserves all existing functionality while providing clean separation.
    """
    
    def __init__(
        self,
        draft_repository: IDraftRepository,
        ui_presenter: IUIPresenter,
        match_recorder: IMatchRecorder,
        balance_calculator: IBalanceCalculator,
        notification_service: INotificationService,
        thread_service: IThreadService
    ):
        self._draft_repository = draft_repository
        self._ui_presenter = ui_presenter
        self._match_recorder = match_recorder
        self._balance_calculator = balance_calculator
        self._notification_service = notification_service
        self._thread_service = thread_service
        
        # Domain services
        self._orchestrator = DraftOrchestrator()
        self._captain_service = CaptainService()
        self._team_service = TeamService()
        self._validation_service = ValidationService()
    
    # ====================
    # Draft Lifecycle
    # ====================
    
    async def create_draft(
        self,
        channel_id: int,
        guild_id: int,
        team_size: int = 6,
        started_by_user_id: Optional[int] = None,
        is_test_mode: bool = False,
        is_join_based: bool = False
    ) -> DraftDTO:
        """Create a new draft session"""
        # Validate parameters
        validation_errors = self._validation_service.validate_draft_creation(
            channel_id, guild_id, team_size
        )
        if validation_errors:
            raise DraftError(f"Invalid draft parameters: {', '.join(validation_errors)}")
        
        # Check if draft already exists
        existing_draft = await self._draft_repository.get_draft(channel_id)
        if existing_draft:
            raise DraftError("A draft is already active in this channel")
        
        # Create draft
        draft = self._orchestrator.create_draft(
            channel_id=channel_id,
            guild_id=guild_id,
            team_size=team_size,
            started_by_user_id=started_by_user_id,
            is_test_mode=is_test_mode
        )
        
        # For regular drafts, prepare thread creation immediately
        # For join-based drafts, threads will be created when lobby is full
        if not is_join_based:
            self._orchestrator.prepare_thread_creation(draft)
        
        # Save draft
        await self._draft_repository.save_draft(draft)
        
        # Create thread if ready (only for non-join-based drafts)
        if not is_join_based and draft.thread_ready_for_creation and draft.thread_name:
            team_format = f"{draft.team_size}v{draft.team_size}"
            player_names = [player.display_name for player in draft.players.values()]
            
            thread_id = await self._thread_service.create_draft_thread(
                channel_id=draft.channel_id,
                thread_name=draft.thread_name,
                team_format=team_format,
                players=player_names
            )
            
            if thread_id:
                draft.thread_id = thread_id
                await self._draft_repository.save_draft(draft)
        
        # Show UI
        draft_dto = DraftDTO.from_domain(draft)
        await self._ui_presenter.show_draft_lobby(draft_dto)
        
        return draft_dto
    
    async def create_manual_draft_with_players(
        self,
        channel_id: int,
        guild_id: int,
        players: List[Tuple[int, str]],  # (user_id, display_name)
        team_size: int = 6,
        started_by_user_id: Optional[int] = None,
        is_test_mode: bool = False
    ) -> DraftDTO:
        """Create a manual draft with specific players already added"""
        # Validate parameters
        validation_errors = self._validation_service.validate_draft_creation(
            channel_id, guild_id, team_size
        )
        if validation_errors:
            raise DraftError(f"Invalid draft parameters: {', '.join(validation_errors)}")
            
        # Validate player count
        expected_players = team_size * 2
        if len(players) != expected_players:
            raise DraftError(f"Expected {expected_players} players for {team_size}v{team_size}, got {len(players)}")
        
        # Check if draft already exists
        existing_draft = await self._draft_repository.get_draft(channel_id)
        if existing_draft:
            raise DraftError("A draft is already active in this channel")
        
        # Create draft
        draft = self._orchestrator.create_draft(
            channel_id=channel_id,
            guild_id=guild_id,
            team_size=team_size,
            started_by_user_id=started_by_user_id,
            is_test_mode=is_test_mode
        )
        
        # Add all players to the draft
        for user_id, display_name in players:
            player = Player(
                user_id=user_id,
                username=display_name,
                team=None,
                selected_servant=None
            )
            draft.add_player(player)
        
        # Save draft
        await self._draft_repository.save_draft(draft)
        
        # Show appropriate UI based on draft state
        draft_dto = DraftDTO.from_domain(draft)
        if draft.can_start:
            # Draft is full - start captain voting immediately (legacy behavior)
            await self._ui_presenter.show_captain_voting(draft_dto)
        else:
            # Draft not full - show lobby for more players to join
            await self._ui_presenter.show_draft_lobby(draft_dto)
        
        return draft_dto
    
    async def create_join_based_draft(
        self,
        channel_id: int,
        guild_id: int,
        total_players: int,
        started_by_user_id: Optional[int] = None
    ) -> DraftDTO:
        """Create a join-based draft that starts when enough players join"""
        # Validate parameters
        validation_errors = self._validation_service.validate_join_based_draft(total_players)
        if validation_errors:
            raise DraftError(f"Invalid join draft parameters: {', '.join(validation_errors)}")
        
        # Check if draft already exists
        existing_draft = await self._draft_repository.get_draft(channel_id)
        if existing_draft:
            raise DraftError("A draft is already active in this channel")
        
        # Create draft
        draft = self._orchestrator.create_join_based_draft(
            channel_id=channel_id,
            guild_id=guild_id,
            total_players=total_players,
            started_by_user_id=started_by_user_id
        )
        
        # Prepare thread creation for draft 
        self._orchestrator.prepare_thread_creation(draft)
        
        # Save draft
        await self._draft_repository.save_draft(draft)
        
        # Create thread if ready 
        if draft.thread_ready_for_creation and draft.thread_name:
            team_format = f"{draft.team_size}v{draft.team_size}"
            player_names = [player.display_name for player in draft.players.values()]
            
            thread_id = await self._thread_service.create_draft_thread(
                channel_id=draft.channel_id,
                thread_name=draft.thread_name,
                team_format=team_format,
                players=player_names
            )
            
            if thread_id:
                draft.thread_id = thread_id
                await self._draft_repository.save_draft(draft)
        
        # Show UI
        draft_dto = DraftDTO.from_domain(draft)
        await self._ui_presenter.show_draft_lobby(draft_dto)
        
        return draft_dto
    
    async def start_join_draft(
        self,
        channel_id: int,
        guild_id: int,
        total_players: int,
        started_by_user_id: Optional[int] = None
    ) -> DraftDTO:
        """Start a join-based draft that shows lobby in main channel"""
        if total_players % 2 != 0 or total_players <= 0:
            raise DraftError("Total players must be a positive even number")
        
        team_size = total_players // 2
        
        # Create join-based draft (no thread initially)
        draft_dto = await self.create_draft(
            channel_id=channel_id,
            guild_id=guild_id,
            team_size=team_size,
            started_by_user_id=started_by_user_id,
            is_test_mode=False,
            is_join_based=True
        )
        
        # Set join target
        draft = await self._draft_repository.get_draft(channel_id)
        if draft:
            draft.join_target_total_players = total_players
            await self._draft_repository.save_draft(draft)
        
        return draft_dto
    
    async def join_draft(self, user_id: int, username: str, channel_id: int) -> JoinResult:
        """Add a player to the draft - preserves existing join logic"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return JoinResult(
                success=False,
                message="No active draft in this channel",
                error_code="NO_DRAFT"
            )
        
        # Validate join attempt
        validation_errors = self._validation_service.validate_player_addition(
            draft, user_id, username
        )
        if validation_errors:
            return JoinResult(
                success=False,
                message=validation_errors[0],  # Return first error
                error_code="VALIDATION_FAILED"
            )
        
        try:
            # Add player to draft
            self._orchestrator.add_player_to_draft(draft, user_id, username)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Check if should auto-start
            should_auto_start = (
                draft.join_target_total_players and 
                len(draft.join_user_ids) >= draft.join_target_total_players
            )
            
            # Update UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.update_draft_status(draft_dto)
            
            return JoinResult(
                success=True,
                message="Successfully joined the draft!",
                should_update_embed=True,
                should_auto_start=should_auto_start
            )
            
        except DraftError as e:
            return JoinResult(
                success=False,
                message=str(e),
                error_code="DRAFT_ERROR"
            )
    
    async def finalize_join_and_start(self, channel_id: int) -> bool:
        """Finalize join process and start draft - creates thread and starts captain voting"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return False
        
        # Players are already created with correct usernames during join process
        # Just need to clear the join data since we're starting the actual draft
        draft.join_user_ids.clear()
        draft.join_target_total_players = None
        
        # Now create the thread (legacy behavior)
        self._orchestrator.prepare_thread_creation(draft)
        
        if draft.thread_ready_for_creation and draft.thread_name:
            team_format = f"{draft.team_size}v{draft.team_size}"
            player_names = [player.display_name for player in draft.players.values()]
            
            thread_id = await self._thread_service.create_draft_thread(
                channel_id=draft.channel_id,
                thread_name=draft.thread_name,
                team_format=team_format,
                players=player_names
            )
            
            if thread_id:
                draft.thread_id = thread_id
        
        # Start captain voting
        self._orchestrator.start_captain_voting(draft)
        
        # Save updated draft
        await self._draft_repository.save_draft(draft)
        
        # Update UI to show captain voting
        draft_dto = DraftDTO.from_domain(draft)
        await self._ui_presenter.update_draft_status(draft_dto)
        
        return True
    
    async def leave_draft(self, user_id: int, channel_id: int) -> JoinResult:
        """Remove a player from the draft"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return JoinResult(
                success=False,
                message="No active draft in this channel",
                error_code="NO_DRAFT"
            )
        
        # Validate removal
        validation_errors = self._validation_service.validate_player_removal(draft, user_id)
        if validation_errors:
            return JoinResult(
                success=False,
                message=validation_errors[0],
                error_code="VALIDATION_FAILED"
            )
        
        try:
            # Remove player
            self._orchestrator.remove_player_from_draft(draft, user_id)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Update UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.update_draft_status(draft_dto)
            
            return JoinResult(
                success=True,
                message="Left the draft",
                should_update_embed=True
            )
            
        except DraftError as e:
            return JoinResult(
                success=False,
                message=str(e),
                error_code="DRAFT_ERROR"
            )
    
    # ====================
    # Captain Operations
    # ====================
    
    async def vote_for_captain(
        self,
        channel_id: int,
        voter_id: int,
        candidate_id: int,
        current_user_votes: Set[int]
    ) -> VoteResult:
        """Cast a vote for captain - preserves existing voting logic"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return VoteResult(
                success=False,
                message="No active draft in this channel",
                error_code="NO_DRAFT"
            )
        
        # Validate vote
        validation_errors = self._validation_service.validate_captain_vote(
            draft, voter_id, candidate_id, current_user_votes
        )
        if validation_errors:
            return VoteResult(
                success=False,
                message=validation_errors[0],
                error_code="VALIDATION_FAILED"
            )
        
        # This would typically be managed by the UI presenter
        # We're preserving the existing pattern where votes are tracked by UI
        # but validation happens through the service
        
        # The actual vote casting logic would be coordinated by the presenter
        # since it involves UI state management
        
        return VoteResult(
            success=True,
            message="Vote validation passed",
            votes_cast=len(current_user_votes)
        )
    
    async def finalize_captain_selection(
        self,
        channel_id: int,
        user_votes: Dict[int, Set[int]]
    ) -> List[int]:
        """Finalize captain selection based on votes"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            raise DraftError("No active draft in this channel")
        
        # Convert Set to List for captain service
        user_votes_list = {k: list(v) for k, v in user_votes.items()}
        
        # Finalize selection
        captain_ids = self._captain_service.finalize_captain_selection(draft, user_votes_list)
        
        # Transition to servant ban phase with full workflow (system bans + dice + captain ban setup)
        await self.transition_to_servant_ban_phase(channel_id)
        
        return captain_ids
    
    async def ban_servant(
        self,
        channel_id: int,
        captain_id: int,
        servant_name: str
    ) -> SelectionResult:
        """Perform captain servant ban"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return SelectionResult(
                success=False,
                message="No active draft in this channel",
                error_code="NO_DRAFT"
            )
        
        # Validate ban
        validation_errors = self._validation_service.validate_servant_ban(
            draft, captain_id, servant_name
        )
        if validation_errors:
            return SelectionResult(
                success=False,
                message=validation_errors[0],
                error_code="VALIDATION_FAILED"
            )
        
        try:
            # Perform ban
            success, message = self._captain_service.perform_captain_ban(
                draft, captain_id, servant_name
            )
            
            if not success:
                return SelectionResult(
                    success=False,
                    message=message,
                    error_code="BAN_FAILED"
                )
            
            # Check if ban phase is complete
            should_advance = self._captain_service.is_captain_ban_phase_complete(draft)
            if should_advance:
                self._orchestrator.complete_servant_ban_phase(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Update UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.update_draft_status(draft_dto)
            
            return SelectionResult(
                success=True,
                message=message,
                should_advance_phase=should_advance
            )
            
        except DraftError as e:
            return SelectionResult(
                success=False,
                message=str(e),
                error_code="DRAFT_ERROR"
            )
    
    # ====================
    # Servant Selection
    # ====================
    
    async def select_servant(
        self,
        channel_id: int,
        user_id: int,
        servant_name: str
    ) -> SelectionResult:
        """Select servant for player - preserves existing selection logic"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return SelectionResult(
                success=False,
                message="No active draft in this channel",
                error_code="NO_DRAFT"
            )
        
        # Validate selection
        validation_errors = self._validation_service.validate_servant_selection(
            draft, user_id, servant_name
        )
        if validation_errors:
            return SelectionResult(
                success=False,
                message=validation_errors[0],
                error_code="VALIDATION_FAILED"
            )
        
        try:
            # Assign servant
            draft.assign_servant_to_player(user_id, servant_name)
            draft.selection_progress[user_id] = True
            
            # Check if selection phase is complete
            should_advance = self._orchestrator.can_advance_to_next_phase(draft)
            if should_advance:
                self._orchestrator.complete_servant_selection(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Update UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.update_draft_status(draft_dto)
            
            return SelectionResult(
                success=True,
                message=f"Selected {servant_name}",
                servant_selected=servant_name,
                selection_completed=True,
                should_advance_phase=should_advance
            )
            
        except DraftError as e:
            return SelectionResult(
                success=False,
                message=str(e),
                error_code="DRAFT_ERROR"
            )
    
    # ====================
    # Team Selection
    # ====================
    
    async def assign_player_to_team(
        self,
        channel_id: int,
        captain_id: int,
        player_id: int
    ) -> TeamAssignmentResult:
        """Assign player to captain's team - preserves existing assignment logic"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return TeamAssignmentResult(
                success=False,
                message="No active draft in this channel",
                error_code="NO_DRAFT"
            )
        
        # Validate assignment
        validation_errors = self._validation_service.validate_team_assignment(
            draft, captain_id, player_id
        )
        if validation_errors:
            return TeamAssignmentResult(
                success=False,
                message=validation_errors[0],
                error_code="VALIDATION_FAILED"
            )
        
        try:
            # Assign player
            success, message = self._team_service.assign_player_to_captain_team(
                draft, captain_id, player_id
            )
            
            if not success:
                return TeamAssignmentResult(
                    success=False,
                    message=message,
                    error_code="ASSIGNMENT_FAILED"
                )
            
            captain_team = draft.get_captain_team(captain_id)
            
            # Advance picking turn
            next_captain = self._team_service.advance_picking_turn(draft)
            
            # Check if team selection is complete
            should_advance = self._team_service.is_team_selection_complete(draft)
            if should_advance:
                self._orchestrator.complete_team_selection(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Update UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.update_draft_status(draft_dto)
            
            return TeamAssignmentResult(
                success=True,
                message=message,
                player_assigned=player_id,
                team_number=captain_team,
                assignment_completed=True,
                should_advance_phase=should_advance
            )
            
        except DraftError as e:
            return TeamAssignmentResult(
                success=False,
                message=str(e),
                error_code="DRAFT_ERROR"
            )
    
    async def confirm_captain_team_selections(
        self,
        channel_id: int,
        captain_id: int,
        selected_player_ids: List[int]
    ) -> bool:
        """Confirm captain's batch team selections (legacy batch confirmation behavior)"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            if draft.phase != DraftPhase.TEAM_SELECTION:
                return False
            
            # Validate captain
            if not draft.is_captain(captain_id):
                return False
            
            # Validate it's captain's turn
            if draft.current_picking_captain != captain_id:
                return False
            
            # Get captain's team
            captain_team = draft.get_captain_team(captain_id)
            if not captain_team:
                return False
            
            # Validate selection count matches pattern requirements
            team_size = draft.team_size
            round_num = draft.team_selection_round
            
            # Get expected picks for this round using team selection service
            round_info = self._team_service.get_round_info(team_size, round_num)
            is_first_pick = captain_id == draft.first_pick_captain
            expected_picks = round_info["first_pick"] if is_first_pick else round_info["second_pick"]
            
            if len(selected_player_ids) != expected_picks:
                return False
            
            # Assign all selected players to captain's team
            for player_id in selected_player_ids:
                player = draft.get_player(player_id)
                if not player or player.is_assigned_to_team:
                    return False
                
                # Assign player to team
                draft.assign_player_to_team(captain_id, player_id, captain_team)
            
            # Update picks for this round
            draft.picks_this_round[captain_id] = draft.picks_this_round.get(captain_id, 0) + len(selected_player_ids)
            
            # Clear pending selections for this captain
            draft.pending_team_selections[captain_id] = []
            
            # Check if round is complete and advance if needed
            should_advance = self._team_service.is_team_selection_complete(draft)
            if should_advance:
                self._orchestrator.complete_team_selection(draft)
            else:
                # Advance to next captain or next round
                self._team_service.advance_team_selection_turn(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Update UI based on state
            draft_dto = DraftDTO.from_domain(draft)
            if should_advance and draft.phase == DraftPhase.COMPLETED:
                await self._ui_presenter.show_game_results(draft_dto)
            else:
                await self._ui_presenter.show_team_selection(draft_dto)
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to confirm captain team selections: {e}")
            return False
    
    # ====================
    # Draft Management
    # ====================
    
    async def get_draft_status(self, channel_id: int) -> Optional[DraftDTO]:
        """Get current draft status"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return None
        
        return DraftDTO.from_domain(draft)
    
    async def cancel_draft(self, channel_id: int, user_id: int) -> bool:
        """Cancel an active draft"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return False
        
        # Check permissions (preserve existing permission logic)
        if draft.started_by_user_id and draft.started_by_user_id != user_id:
            # Only starter can cancel (or bot owners, but that's handled at UI level)
            return False
        
        # Delete draft
        await self._draft_repository.delete_draft(channel_id)
        
        return True
    
    async def validate_draft(self, channel_id: int) -> ValidationResult:
        """Validate draft state"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return ValidationResult(
                is_valid=False,
                errors=["No draft found"],
                warnings=[]
            )
        
        errors = self._validation_service.validate_draft_state(draft)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=[]
        )
    
    async def record_match_result(
        self,
        channel_id: int,
        winner: Optional[int],
        score: Optional[str] = None
    ) -> bool:
        """Record match result for completed draft - preserves legacy behavior"""
        try:
            # Check for active draft first
            draft = await self._draft_repository.get_draft(channel_id)
            
            if draft:
                # Check if already recorded
                if draft.outcome_recorded:
                    raise DraftError("이미 결과가 기록되었어")
                
                # Must be completed to record result
                if draft.phase != DraftPhase.COMPLETED:
                    return False
                
                # Record match
                await self._match_recorder.record_match(draft, winner, score)
                
                # Mark outcome as recorded
                draft.outcome_recorded = True
                await self._draft_repository.save_draft(draft)
                
                return True
            else:
                # No active draft - try to record for recently completed draft
                # Use legacy match_id format: guild_id:channel_id:
                match_id_prefix = f"0:{channel_id}:"  # Default guild_id to 0
                
                # Create a minimal match record for recently completed drafts
                # This preserves the legacy behavior of recording results even after cleanup
                await self._match_recorder.record_match_outcome(match_id_prefix, winner, score)
                return True
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to record match result: {e}")
            return False
    
    async def force_cleanup_draft(
        self,
        channel_id: int,
        admin_user_id: int
    ) -> bool:
        """Force cleanup a stuck draft (admin only) - preserves legacy behavior"""
        try:
            # Check if draft exists
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Audit log the force cleanup
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Force cleanup initiated by admin {admin_user_id} for channel {channel_id}")
            logger.info(f"Draft state: phase={draft.phase.value}, players={len(draft.players)}, team_size={draft.team_size}")
            
            # Clean up the draft
            await self._draft_repository.delete_draft(channel_id)
            
            # Notify UI presenter to cleanup views
            try:
                await self._ui_presenter.cleanup_channel(channel_id)
            except Exception as e:
                logger.warning(f"UI cleanup failed during force cleanup: {e}")
            
            logger.info(f"Force cleanup completed for channel {channel_id}")
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Force cleanup failed: {e}")
            return False
    
    async def show_enhanced_progress(
        self,
        channel_id: int,
        progress_type: str,
        **kwargs
    ) -> bool:
        """Show enhanced progress tracking for different phases"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            draft_dto = DraftDTO.from_domain(draft)
            
            if progress_type == "captain_voting":
                progress_details = {
                    "total_votes_needed": len(draft.players) * 2,  # Each player votes for 2 captains
                    "votes_cast": sum(draft.captain_voting_progress.values()),
                    "progress_by_player": draft.captain_voting_progress,
                    "time_remaining": kwargs.get("time_remaining", 0)
                }
                await self._ui_presenter.show_captain_voting_progress(draft_dto, progress_details)
            
            elif progress_type == "team_selection":
                round_info = {
                    "round": draft.team_selection_round,
                    "current_captain": draft.current_picking_captain,
                    "picks_made": draft.picks_this_round,
                    "pattern": self._orchestrator.get_team_selection_pattern(draft.team_size),
                    "pending_selections": draft.pending_team_selections
                }
                await self._ui_presenter.show_team_selection_progress(draft_dto, round_info)
            
            elif progress_type == "dice_roll":
                await self._ui_presenter.show_dice_roll_results(draft_dto, draft.captain_ban_dice_rolls)
            
            elif progress_type == "system_bans":
                await self._ui_presenter.show_system_ban_results(draft_dto, draft.system_bans)
            
            elif progress_type == "auto_cloak_bans":
                await self._ui_presenter.show_system_ban_results(draft_dto, draft.reselection_auto_bans)
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show enhanced progress: {e}")
            return False
    
    # ====================
    # Auto-Balance Integration
    # ====================
    
    async def get_team_balance_suggestions(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get team balance suggestions from auto-balance service"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return None
        
        return await self._balance_calculator.calculate_team_balance(draft)
    
    async def perform_auto_balance(self, channel_id: int, algorithm: str) -> Optional[Dict[str, Any]]:
        """Perform automatic team balancing"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return None
        
        balance_result = await self._balance_calculator.auto_balance_teams(draft, algorithm)
        
        # Store result for review
        draft.auto_balance_result = balance_result
        await self._draft_repository.save_draft(draft)
        
        return balance_result
    
    # ====================
    # New Phase Workflows
    # ====================
    
    async def transition_to_servant_ban_phase(
        self,
        channel_id: int
    ) -> bool:
        """Transition draft from captain voting to servant ban phase"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Transition to servant ban phase (assigns captains to teams)
            self._orchestrator.transition_to_servant_ban_phase(draft)
            
            # Perform complete servant ban phase (system + captain bans)
            self._orchestrator.complete_servant_ban_phase(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Show servant ban UI (system bans + captain ban interface)
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.show_servant_ban_phase(draft_dto)
            
            # Show dice roll results
            if draft.captain_ban_dice_rolls:
                await self.show_enhanced_progress(channel_id, "dice_roll")
            
            # Show system ban results
            if draft.system_bans:
                await self.show_enhanced_progress(channel_id, "system_bans")
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to transition to servant ban phase: {e}")
            return False
    
    async def apply_captain_ban(
        self,
        channel_id: int,
        captain_id: int,
        servant_name: str
    ) -> bool:
        """Apply a captain ban during servant ban phase"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Apply the ban
            success = self._orchestrator.apply_captain_ban(draft, captain_id, servant_name)
            if not success:
                return False
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Check if all captain bans are complete
            if self._orchestrator.are_captain_bans_complete(draft):
                # Transition to servant selection phase
                await self.transition_to_servant_selection_phase(channel_id)
            else:
                # Update captain ban progress UI
                draft_dto = DraftDTO.from_domain(draft)
                await self._ui_presenter.update_captain_ban_progress(draft_dto)
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to apply captain ban: {e}")
            return False
    
    async def transition_to_servant_selection_phase(
        self,
        channel_id: int
    ) -> bool:
        """Transition to servant selection phase after bans complete"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Transition phase
            self._orchestrator.transition_to_servant_selection_phase(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Show servant selection UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.show_servant_selection(draft_dto)
            
            # Start background timeout monitoring (legacy behavior)
            asyncio.create_task(self._monitor_selection_timeout(channel_id))
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to transition to servant selection phase: {e}")
            return False
    
    async def apply_servant_selection(
        self,
        channel_id: int,
        user_id: int,
        servant_name: str
    ) -> bool:
        """Apply a player's servant selection"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Apply selection
            from ..domain.services.servant_service import ServantService
            servant_service = ServantService()
            success = servant_service.apply_servant_selection(draft, user_id, servant_name)
            
            if not success:
                return False
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Check if all selections are complete
            if servant_service.is_servant_selection_complete(draft):
                # Check for conflicts and transition appropriately
                await self.check_conflicts_and_transition(channel_id)
            else:
                # Update selection progress
                draft_dto = DraftDTO.from_domain(draft)
                await self._ui_presenter.update_servant_selection_progress(draft_dto)
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to apply servant selection: {e}")
            return False
    
    async def check_conflicts_and_transition(
        self,
        channel_id: int
    ) -> bool:
        """Check for servant conflicts and transition to appropriate next phase"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Check conflicts and transition
            has_conflicts = self._orchestrator.check_servant_conflicts_and_transition(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            if has_conflicts:
                # Show reselection UI with auto-cloak bans applied
                draft_dto = DraftDTO.from_domain(draft)
                await self._ui_presenter.show_servant_reselection(draft_dto)
                
                # Start background timeout monitoring for reselection (legacy behavior)
                asyncio.create_task(self._monitor_selection_timeout(channel_id))
                
                # Show auto-cloak ban results if any
                if draft.reselection_auto_bans:
                    await self.show_enhanced_progress(channel_id, "auto_cloak_bans")
            else:
                # No conflicts - move to team selection
                draft_dto = DraftDTO.from_domain(draft)
                await self._ui_presenter.show_team_selection(draft_dto)
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to check conflicts and transition: {e}")
            return False
    
    async def resolve_servant_conflicts(
        self,
        channel_id: int
    ) -> bool:
        """Complete servant reselection and move to team selection"""
        try:
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return False
            
            # Transition to team selection phase
            self._orchestrator.transition_to_team_selection_phase(draft)
            
            # Save updated draft
            await self._draft_repository.save_draft(draft)
            
            # Show team selection UI
            draft_dto = DraftDTO.from_domain(draft)
            await self._ui_presenter.show_team_selection(draft_dto)
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to resolve servant conflicts: {e}")
            return False

    async def _monitor_selection_timeout(self, channel_id: int) -> None:
        """
        Monitor 90-second timeout for servant selection/reselection phase.
        Legacy behavior: automatically assign random servants to incomplete players.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Wait for 90 seconds (legacy timeout)
            await asyncio.sleep(90)
            
            draft = await self._draft_repository.get_draft(channel_id)
            if not draft:
                return
            
            # Check if we're still in a selection phase
            from ..domain.entities.draft_phase import DraftPhase
            if draft.phase not in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
                logger.info(f"Draft {channel_id}: Selection phase completed before timeout")
                return
            
            # Handle timeout based on current phase
            await self._handle_selection_timeout(channel_id, draft)
            
        except asyncio.CancelledError:
            # Timeout was cancelled (phase completed normally)
            logger.info(f"Draft {channel_id}: Selection timeout monitoring cancelled")
        except Exception as e:
            logger.error(f"Draft {channel_id}: Error in selection timeout monitoring: {e}")

    async def _handle_selection_timeout(self, channel_id: int, draft) -> None:
        """
        Handle 90-second timeout by randomly assigning servants to incomplete players.
        Legacy behavior: excludes banned and already selected servants.
        """
        import logging
        import random
        logger = logging.getLogger(__name__)
        
        try:
            from ..domain.services.servant_service import ServantService
            servant_service = ServantService()
            
            # Get incomplete players based on phase
            incomplete_players = []
            
            from ..domain.entities.draft_phase import DraftPhase
            
            if draft.phase == DraftPhase.SERVANT_SELECTION:
                # All players who haven't selected or confirmed servants
                for user_id in draft.players.keys():
                    if not draft.selection_progress.get(user_id, False):
                        incomplete_players.append(user_id)
            elif draft.phase == DraftPhase.SERVANT_RESELECTION:
                # Players who were conflicted and haven't reselected
                for servant_conflicts in draft.conflicted_servants.values():
                    for user_id in servant_conflicts:
                        if not draft.selection_progress.get(user_id, False):
                            incomplete_players.append(user_id)
            
            if not incomplete_players:
                logger.info(f"Draft {channel_id}: No incomplete players found during timeout")
                return
            
            logger.info(f"Draft {channel_id}: Timeout reached, assigning random servants to {len(incomplete_players)} players")
            
            # Get all available servants (excluding banned and confirmed)
            all_servants = set()
            for servants in draft.servant_categories.values():
                all_servants.update(servants)
            
            # Remove banned servants
            available_servants = all_servants - draft.banned_servants
            
            # Remove already confirmed servants
            if hasattr(draft, 'confirmed_servants'):
                available_servants = available_servants - set(draft.confirmed_servants.values())
            
            # Remove reselection auto-bans if in reselection phase
            if draft.phase == DraftPhase.SERVANT_RESELECTION and hasattr(draft, 'reselection_auto_bans'):
                available_servants = available_servants - draft.reselection_auto_bans
            
            available_servants_list = list(available_servants)
            
            if not available_servants_list:
                logger.error(f"Draft {channel_id}: No available servants for random assignment")
                return
            
            # Assign random servants to incomplete players
            assignments = {}
            for user_id in incomplete_players:
                if available_servants_list:
                    random_servant = random.choice(available_servants_list)
                    available_servants_list.remove(random_servant)  # Prevent duplicates
                    assignments[user_id] = random_servant
                    
                    # Apply the selection
                    servant_service.apply_servant_selection(draft, user_id, random_servant)
                    draft.selection_progress[user_id] = True
                    
                    # Log the assignment
                    player_name = draft.players[user_id].username if user_id in draft.players else f"User{user_id}"
                    logger.info(f"Draft {channel_id}: Randomly assigned {random_servant} to {player_name}")
            
            # Save the updated draft
            await self._draft_repository.save_draft(draft)
            
            # Send timeout announcement (legacy format) to the correct thread/channel
            timeout_embed = discord.Embed(
                title="⏰ 제한 시간 종료!",
                description="다음 플레이어들에게 랜덤 서번트가 배정되었어:" if assignments else "모든 플레이어가 선택을 완료했어.",
                color=0xf39c12  # WARNING_COLOR
            )
            
            if assignments:
                assignment_text = ""
                for user_id, servant in assignments.items():
                    player_name = draft.players[user_id].username if user_id in draft.players else f"User{user_id}"
                    assignment_text += f"• **{player_name}**: {servant}\n"
                timeout_embed.add_field(
                    name="자동 배정된 서번트",
                    value=assignment_text.strip(),
                    inline=False
                )
            
            # Send to thread if available, otherwise to main channel (same as other draft messages)
            await self._thread_service.send_to_thread_with_fallback(
                channel_id=draft.channel_id,
                thread_id=draft.thread_id,
                embed=timeout_embed
            )
            
            # Continue with phase progression
            if draft.phase == DraftPhase.SERVANT_SELECTION:
                # Check for conflicts and transition
                await self.check_conflicts_and_transition(channel_id)
            elif draft.phase == DraftPhase.SERVANT_RESELECTION:
                # Move to team selection
                await self.resolve_servant_conflicts(channel_id)
            
        except Exception as e:
            logger.error(f"Draft {channel_id}: Error handling selection timeout: {e}")
