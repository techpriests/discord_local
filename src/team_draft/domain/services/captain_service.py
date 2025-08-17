"""
Captain Service - Domain Service

Handles captain-specific business logic including voting, selection, and captain-related operations.
Preserves all existing captain voting algorithms and logic.
"""

import random
from typing import Dict, List, Set, Tuple, Optional
from ..entities.draft import Draft
from ..entities.draft_phase import DraftPhase
from ..exceptions import (
    InvalidDraftStateError,
    InvalidCaptainError,
    CaptainVotingError,
    PlayerNotFoundError
)


class CaptainService:
    """
    Domain service for captain-related operations.
    
    Preserves all existing captain voting logic and selection algorithms.
    """
    
    def can_vote_for_captain(self, draft: Draft, voter_id: int, candidate_id: int) -> bool:
        """Check if a vote is valid - preserves existing validation logic"""
        # Must be in captain voting phase
        if draft.phase != DraftPhase.CAPTAIN_VOTING:
            return False
        
        # Voter must be in the draft
        if voter_id not in draft.players:
            return False
        
        # Candidate must be in the draft
        if candidate_id not in draft.players:
            return False
        
        return True
    
    def get_current_votes_for_user(self, user_votes: Dict[int, Set[int]], user_id: int) -> int:
        """Get current vote count for a user - preserves existing logic"""
        return len(user_votes.get(user_id, set()))
    
    def can_cast_vote(self, user_votes: Dict[int, Set[int]], user_id: int, vote_limit: int = 2) -> bool:
        """Check if user can cast another vote - preserves existing logic"""
        return self.get_current_votes_for_user(user_votes, user_id) < vote_limit
    
    def cast_vote(
        self, 
        draft: Draft, 
        user_votes: Dict[int, Set[int]], 
        voter_id: int, 
        candidate_id: int
    ) -> Tuple[bool, str]:
        """
        Cast a vote for captain - preserves existing voting logic
        
        Returns:
            Tuple of (success, message)
        """
        if not self.can_vote_for_captain(draft, voter_id, candidate_id):
            return False, "Invalid vote"
        
        # Initialize user votes if needed
        if voter_id not in user_votes:
            user_votes[voter_id] = set()
        
        # Check if already voted for this candidate
        if candidate_id in user_votes[voter_id]:
            # Remove vote (toggle off)
            user_votes[voter_id].remove(candidate_id)
            # Update progress tracking
            draft.captain_voting_progress[voter_id] = len(user_votes[voter_id])
            candidate_name = draft.players[candidate_id].username
            return True, f"{candidate_name}에 대한 투표를 취소했어."
        
        # Check vote limit
        if not self.can_cast_vote(user_votes, voter_id):
            return False, "최대 2명까지만 투표할 수 있어."
        
        # Cast vote
        user_votes[voter_id].add(candidate_id)
        # Update progress tracking
        draft.captain_voting_progress[voter_id] = len(user_votes[voter_id])
        candidate_name = draft.players[candidate_id].username
        return True, f"{candidate_name}에게 투표했어!"
    
    def calculate_vote_results(
        self, 
        draft: Draft, 
        user_votes: Dict[int, Set[int]]
    ) -> Dict[int, int]:
        """
        Calculate final vote counts - preserves existing algorithm
        
        Returns:
            Dict of candidate_id -> vote_count
        """
        vote_counts: Dict[int, int] = {}
        
        for voter_id, votes in user_votes.items():
            # Only count votes from draft participants
            if voter_id in draft.players:
                for candidate_id in votes:
                    # Only count votes for draft participants
                    if candidate_id in draft.players:
                        vote_counts[candidate_id] = vote_counts.get(candidate_id, 0) + 1
        
        return vote_counts
    
    def select_captains_from_votes(
        self, 
        draft: Draft, 
        user_votes: Dict[int, Set[int]]
    ) -> List[int]:
        """
        Select captains based on voting results - preserves existing selection logic
        
        Returns:
            List of 2 captain IDs
        """
        vote_counts = self.calculate_vote_results(draft, user_votes)
        
        # Sort candidates by vote count (highest first)
        sorted_candidates = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        
        if len(sorted_candidates) < 2:
            # Fall back to first 2 players if not enough votes - preserves existing fallback
            captain_ids = list(draft.players.keys())[:2]
        else:
            # Handle ties at the top - preserves existing tie-breaking logic
            top_candidates = []
            if len(sorted_candidates) >= 2:
                top_vote_count = sorted_candidates[0][1]
                second_vote_count = sorted_candidates[1][1]
                
                # Get all candidates with top vote count
                top_tier = [cid for cid, votes in sorted_candidates if votes == top_vote_count]
                
                if len(top_tier) >= 2:
                    # Multiple tied for first - randomly select 2
                    captain_ids = random.sample(top_tier, 2)
                else:
                    # One clear winner, check for ties in second place
                    first_captain = top_tier[0]
                    second_tier = [cid for cid, votes in sorted_candidates if votes == second_vote_count]
                    
                    if len(second_tier) > 1:
                        # Tie for second place - randomly select
                        second_captain = random.choice(second_tier)
                    else:
                        second_captain = second_tier[0] if second_tier else sorted_candidates[1][0]
                    
                    captain_ids = [first_captain, second_captain]
            else:
                captain_ids = [candidate[0] for candidate in sorted_candidates[:2]]
        
        return captain_ids
    
    def finalize_captain_selection(
        self, 
        draft: Draft, 
        user_votes: Dict[int, Set[int]]
    ) -> List[int]:
        """
        Complete captain selection process - preserves existing logic
        
        Returns:
            List of selected captain IDs
        """
        if draft.phase != DraftPhase.CAPTAIN_VOTING:
            raise InvalidDraftStateError("Not in captain voting phase")
        
        # Select captains
        captain_ids = self.select_captains_from_votes(draft, user_votes)
        
        # Set captains in draft (this will handle team assignments)
        draft.set_captains(captain_ids)
        
        return captain_ids
    
    def determine_ban_order(self, draft: Draft) -> List[int]:
        """
        Determine captain ban order using dice roll - preserves existing logic
        
        Returns:
            List of captain IDs in ban order
        """
        if not draft.teams.both_have_captains:
            raise InvalidCaptainError("Both teams must have captains")
        
        captains = draft.captains.copy()
        
        # Simulate dice roll for ban order - preserves existing randomization
        random.shuffle(captains)
        
        draft.captain_ban_order = captains
        return captains
    
    def can_captain_ban(self, draft: Draft, captain_id: int) -> bool:
        """Check if captain can perform ban - preserves existing validation"""
        if draft.phase != DraftPhase.SERVANT_BAN:
            return False
        
        if not draft.is_captain(captain_id):
            return False
        
        # Check if it's this captain's turn to ban
        if draft.current_banning_captain is not None:
            return draft.current_banning_captain == captain_id
        
        # Check if captain has already banned
        return not draft.captain_ban_progress.get(captain_id, False)
    
    def perform_captain_ban(
        self, 
        draft: Draft, 
        captain_id: int, 
        servant_name: str
    ) -> Tuple[bool, str]:
        """
        Perform captain ban - preserves existing ban logic
        
        Returns:
            Tuple of (success, message)
        """
        if not self.can_captain_ban(draft, captain_id):
            return False, "You cannot ban at this time"
        
        if not draft.is_servant_available(servant_name):
            return False, f"{servant_name} is not available for banning"
        
        # Perform the ban
        draft.ban_servant(servant_name, banned_by=captain_id)
        
        # Mark captain as having completed their ban
        draft.captain_ban_progress[captain_id] = True
        
        # Update current banning captain
        ban_order = draft.captain_ban_order or draft.captains
        current_index = ban_order.index(captain_id) if captain_id in ban_order else -1
        
        if current_index != -1 and current_index + 1 < len(ban_order):
            # Next captain's turn
            next_captain = ban_order[current_index + 1]
            if not draft.captain_ban_progress.get(next_captain, False):
                draft.current_banning_captain = next_captain
            else:
                draft.current_banning_captain = None
        else:
            draft.current_banning_captain = None
        
        return True, f"Banned {servant_name}"
    
    def get_captain_ban_status(self, draft: Draft) -> Dict[str, any]:
        """Get current ban phase status - preserves existing status tracking"""
        if draft.phase != DraftPhase.SERVANT_BAN:
            return {"phase": "not_banning"}
        
        status = {
            "phase": "banning",
            "ban_order": draft.captain_ban_order or draft.captains,
            "current_banning_captain": draft.current_banning_captain,
            "captain_progress": dict(draft.captain_ban_progress),
            "banned_servants": list(draft.banned_servants),
            "system_bans": draft.system_bans.copy(),
            "captain_bans": {k: v.copy() for k, v in draft.captain_bans.items()}
        }
        
        # Check if all captains are done
        all_done = all(
            draft.captain_ban_progress.get(captain_id, False) 
            for captain_id in draft.captains
        )
        status["all_captains_done"] = all_done
        
        return status
    
    def is_captain_ban_phase_complete(self, draft: Draft) -> bool:
        """Check if captain ban phase is complete - preserves existing logic"""
        if draft.phase != DraftPhase.SERVANT_BAN:
            return False
        
        return all(
            draft.captain_ban_progress.get(captain_id, False) 
            for captain_id in draft.captains
        )
    
    def get_captain_team_number(self, draft: Draft, captain_id: int) -> Optional[int]:
        """Get team number for a captain"""
        if not draft.is_captain(captain_id):
            return None
        
        player = draft.get_player(captain_id)
        return player.team if player else None
    
    def get_opposing_captain(self, draft: Draft, captain_id: int) -> Optional[int]:
        """Get the opposing captain"""
        if not draft.is_captain(captain_id):
            return None
        
        for other_captain in draft.captains:
            if other_captain != captain_id:
                return other_captain
        
        return None
