"""
Draft Application Service

Main application service that coordinates draft operations.
Acts as the facade for all draft-related use cases and coordinates domain services.
"""

import asyncio
from typing import Dict, List, Optional, Set, Any
from ..domain.entities.draft import Draft
from ..domain.entities.draft_phase import DraftPhase
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
    INotificationService
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
        notification_service: INotificationService
    ):
        self._draft_repository = draft_repository
        self._ui_presenter = ui_presenter
        self._match_recorder = match_recorder
        self._balance_calculator = balance_calculator
        self._notification_service = notification_service
        
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
        is_test_mode: bool = False
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
        
        # Save draft
        await self._draft_repository.save_draft(draft)
        
        # Show UI
        draft_dto = DraftDTO.from_domain(draft)
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
        
        # Save draft
        await self._draft_repository.save_draft(draft)
        
        # Show UI
        draft_dto = DraftDTO.from_domain(draft)
        await self._ui_presenter.show_draft_lobby(draft_dto)
        
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
        
        # Start servant ban phase
        self._orchestrator.start_servant_ban_phase(draft)
        
        # Save updated draft
        await self._draft_repository.save_draft(draft)
        
        # Update UI
        draft_dto = DraftDTO.from_domain(draft)
        await self._ui_presenter.show_servant_selection(draft_dto)
        
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
        """Record match result for completed draft"""
        draft = await self._draft_repository.get_draft(channel_id)
        if not draft:
            return False
        
        if draft.phase != DraftPhase.COMPLETED:
            return False
        
        # Record match
        await self._match_recorder.record_match(draft, winner, score)
        
        # Mark outcome as recorded
        draft.outcome_recorded = True
        await self._draft_repository.save_draft(draft)
        
        return True
    
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
