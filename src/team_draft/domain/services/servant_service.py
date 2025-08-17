"""
Servant Service

Handles servant-related operations including system bans, tier management,
and servant selection logic. Preserves legacy servant system behavior.
"""

import random
from typing import List, Set, Dict, Optional, Any
from ..entities.draft import Draft
from ..exceptions import DraftError


class ServantService:
    """
    Service for managing servant operations.
    
    Handles:
    - Automated system bans by tier
    - Servant availability tracking
    - Tier-based servant selection
    """
    
    def perform_system_bans(self, draft: Draft) -> List[str]:
        """
        Perform automated system bans before captain bans - preserves legacy logic
        
        Legacy system bans:
        - 1 random from S tier (if available)
        - 1 random from A tier (if available) 
        - 1 random from B tier (if available)
        
        Returns:
            List of banned servant names
        """
        system_bans = []
        
        # Get available servants for each tier (exclude already banned)
        available_s_tier = [s for s in draft.servant_tiers["S"] if s in draft.available_servants]
        available_a_tier = [s for s in draft.servant_tiers["A"] if s in draft.available_servants]
        available_b_tier = [s for s in draft.servant_tiers["B"] if s in draft.available_servants]
        
        # 1 random from S tier (if possible)
        if available_s_tier:
            s_ban = random.choice(available_s_tier)
            system_bans.append(s_ban)
            draft.available_servants.discard(s_ban)
            # Remove from other tiers if duplicate
            available_a_tier = [s for s in available_a_tier if s != s_ban]
            available_b_tier = [s for s in available_b_tier if s != s_ban]
        
        # 1 random from A tier (if available)
        if available_a_tier:
            a_ban = random.choice(available_a_tier)
            system_bans.append(a_ban)
            draft.available_servants.discard(a_ban)
            # Remove from B tier if duplicate
            available_b_tier = [s for s in available_b_tier if s != a_ban]
        
        # 1 random from B tier (if available)
        if available_b_tier:
            b_ban = random.choice(available_b_tier)
            system_bans.append(b_ban)
            draft.available_servants.discard(b_ban)
        
        # Store system bans in draft
        draft.system_bans = system_bans
        draft.banned_servants.update(system_bans)
        
        return system_bans
    
    def initialize_servant_availability(self, draft: Draft) -> None:
        """Initialize available servants from all tiers"""
        all_servants = set()
        for tier_servants in draft.servant_tiers.values():
            all_servants.update(tier_servants)
        
        draft.available_servants = all_servants.copy()
        draft.banned_servants = set()
        draft.system_bans = []
    
    def ban_servant(self, draft: Draft, servant_name: str, banned_by: Optional[int] = None) -> bool:
        """
        Ban a specific servant
        
        Args:
            draft: Draft instance
            servant_name: Name of servant to ban
            banned_by: User ID who banned (None for system bans)
            
        Returns:
            True if successfully banned, False if already banned or unavailable
        """
        if servant_name not in draft.available_servants:
            return False
        
        draft.available_servants.discard(servant_name)
        draft.banned_servants.add(servant_name)
        
        # Track who banned it
        if banned_by:
            if not hasattr(draft, 'captain_bans'):
                draft.captain_bans = {}
            if banned_by not in draft.captain_bans:
                draft.captain_bans[banned_by] = []
            draft.captain_bans[banned_by].append(servant_name)
        
        return True
    
    def get_available_servants_by_tier(self, draft: Draft) -> Dict[str, List[str]]:
        """Get available servants organized by tier"""
        available_by_tier = {}
        
        for tier, servants in draft.servant_tiers.items():
            available_by_tier[tier] = [
                servant for servant in servants 
                if servant in draft.available_servants
            ]
        
        return available_by_tier
    
    def get_servant_tier(self, draft: Draft, servant_name: str) -> Optional[str]:
        """Get the tier of a specific servant"""
        for tier, servants in draft.servant_tiers.items():
            if servant_name in servants:
                return tier
        return None
    
    def is_servant_available(self, draft: Draft, servant_name: str) -> bool:
        """Check if a servant is available for selection"""
        return servant_name in draft.available_servants
    
    def get_ban_suggestions(self, draft: Draft, tier: Optional[str] = None) -> List[str]:
        """
        Get suggested servants for banning
        
        Args:
            draft: Draft instance
            tier: Specific tier to suggest from (None for all tiers)
            
        Returns:
            List of suggested servant names
        """
        if tier:
            return [s for s in draft.servant_tiers.get(tier, []) if s in draft.available_servants]
        
        # Return all available servants
        return list(draft.available_servants)
    
    def apply_automatic_cloaking_bans_for_reselection(self, draft: Draft) -> List[str]:
        """
        Apply automatic cloaking bans during re-selection phase if no detection servants confirmed.
        This preserves legacy behavior to reduce second-mover advantage.
        
        Returns:
            List of automatically banned cloaking servants
        """
        auto_bans = []
        
        # Check if any detection servants are confirmed
        confirmed_servants = set(draft.confirmed_servants.values()) if hasattr(draft, 'confirmed_servants') else set()
        has_detection = any(s in draft.detection_servants for s in confirmed_servants)
        
        if not has_detection:
            # Auto-ban available cloaking servants
            auto_bans = [
                s for s in draft.cloaking_servants 
                if s in draft.available_servants and s not in draft.banned_servants
            ]
            
            # Apply the bans
            for servant in auto_bans:
                draft.available_servants.discard(servant)
                draft.banned_servants.add(servant)
            
            # Track these as system bans for reselection
            if not hasattr(draft, 'reselection_auto_bans'):
                draft.reselection_auto_bans = []
            draft.reselection_auto_bans.extend(auto_bans)
        
        return auto_bans
    
    def detect_servant_conflicts(self, draft: Draft) -> Dict[str, List[int]]:
        """
        Detect conflicts in servant selection - multiple players selecting same servant.
        
        Returns:
            Dict of servant_name -> [user_ids] for conflicted servants
        """
        servant_selections = {}
        
        # Count selections per servant (excluding captains and confirmed servants)
        for user_id, player in draft.players.items():
            if not player.is_captain and hasattr(player, 'selected_servant') and player.selected_servant:
                servant = player.selected_servant
                if servant not in servant_selections:
                    servant_selections[servant] = []
                servant_selections[servant].append(user_id)
        
        # Find conflicts (more than 1 player selected same servant)
        conflicts = {
            servant: user_ids 
            for servant, user_ids in servant_selections.items() 
            if len(user_ids) > 1
        }
        
        return conflicts
    
    def resolve_servant_conflicts_with_dice(self, draft: Draft) -> Dict[str, Dict[str, Any]]:
        """
        Resolve conflicts using dice rolls - preserves legacy behavior for 3+ player conflicts.
        
        Returns:
            Dict with conflict resolution results:
            {
                servant_name: {
                    'winner_id': int,
                    'losers': [int],
                    'dice_rolls': {user_id: roll},
                    'attempts': int
                }
            }
        """
        conflicts = self.detect_servant_conflicts(draft)
        resolution_results = {}
        
        for servant, user_ids in conflicts.items():
            # Keep original list for later use (critical for 3+ player scenarios)
            original_conflicted_users = user_ids.copy()
            
            # Roll dice for each conflicted user with tie-breaking
            rolls = {}
            max_attempts = 5  # Prevent infinite loops
            attempt = 0
            current_users = user_ids.copy()  # Users to roll dice for
            
            while attempt < max_attempts:
                # Roll dice for all current users
                for user_id in current_users:
                    rolls[user_id] = random.randint(1, 20)
                
                # Check for ties at the highest roll
                max_roll = max(rolls[uid] for uid in current_users)
                winners = [uid for uid in current_users if rolls[uid] == max_roll]
                
                if len(winners) == 1:
                    # Clear winner found
                    winner_id = winners[0]
                    break
                else:
                    # Tie detected, re-roll only the tied players
                    current_users = winners  # Only re-roll the tied players
                    attempt += 1
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"Dice tie for {servant}, re-rolling attempt {attempt}")
            
            # If still tied after max attempts, use deterministic fallback
            if len(winners) > 1:
                winner_id = min(winners)  # Use lowest user ID as tiebreaker
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Max re-roll attempts reached for {servant}, using user ID tiebreaker")
            
            # Set winner and determine losers - use original list to get ALL losers
            draft.confirmed_servants[winner_id] = servant
            original_losers = [uid for uid in original_conflicted_users if uid != winner_id]
            
            # Reset only the losers (not the winner) - critical for 3+ player scenarios
            for user_id in original_losers:
                player = draft.players.get(user_id)
                if player:
                    player.selected_servant = None
            
            # Update conflicted servants to only include losers who need reselection
            draft.conflicted_servants[servant] = original_losers
            
            # Store resolution result for UI display
            resolution_results[servant] = {
                'winner_id': winner_id,
                'losers': original_losers,
                'dice_rolls': rolls,
                'attempts': attempt + 1
            }
        
        return resolution_results
    
    def apply_servant_selection(self, draft: Draft, user_id: int, servant_name: str) -> bool:
        """
        Apply servant selection for a player, detecting conflicts with comprehensive logging.
        
        Returns:
            True if selection applied successfully, False if servant unavailable
        """
        import logging
        logger = logging.getLogger(__name__)
        
        player = draft.players.get(user_id)
        player_name = player.username if player else f"User{user_id}"
        
        logger.info(f"Servant selection: {player_name} attempting to select {servant_name}")
        
        if not self.is_servant_available(draft, servant_name):
            logger.warning(f"Servant selection: {servant_name} is not available for {player_name}")
            return False
        
        if not player or player.is_captain:
            logger.warning(f"Servant selection: {player_name} is not eligible to select servants (captain or not found)")
            return False
        
        # Log previous selection if any
        if hasattr(player, 'selected_servant') and player.selected_servant:
            logger.info(f"Servant selection: {player_name} changing selection from {player.selected_servant} to {servant_name}")
        else:
            logger.info(f"Servant selection: {player_name} making initial selection of {servant_name}")
        
        # Apply selection
        player.selected_servant = servant_name
        
        # Update conflicts
        old_conflicts = draft.conflicted_servants.copy() if hasattr(draft, 'conflicted_servants') else {}
        draft.conflicted_servants = self.detect_servant_conflicts(draft)
        
        # Log conflict changes
        if draft.conflicted_servants != old_conflicts:
            logger.info(f"Servant selection: Conflicts updated after {player_name}'s selection")
            for servant, user_ids in draft.conflicted_servants.items():
                conflict_names = [
                    next((p.username for p in draft.players.values() if p.user_id == uid), f"User{uid}")
                    for uid in user_ids
                ]
                logger.info(f"  Conflict for {servant}: {', '.join(conflict_names)}")
        
        logger.info(f"Servant selection: Successfully applied {servant_name} for {player_name}")
        return True
    
    def confirm_servant_selection(self, draft: Draft, user_id: int) -> bool:
        """
        Confirm a player's servant selection (no conflicts) with comprehensive logging.
        
        Returns:
            True if confirmed successfully
        """
        import logging
        logger = logging.getLogger(__name__)
        
        player = draft.players.get(user_id)
        player_name = player.username if player else f"User{user_id}"
        
        logger.info(f"Servant confirmation: Attempting to confirm selection for {player_name}")
        
        if not player or not hasattr(player, 'selected_servant') or not player.selected_servant:
            logger.warning(f"Servant confirmation: {player_name} has no servant to confirm")
            return False
        
        servant_name = player.selected_servant
        logger.info(f"Servant confirmation: Confirming {servant_name} for {player_name}")
        
        # Move from selection to confirmed
        draft.confirmed_servants[user_id] = servant_name
        
        # Remove from available servants
        draft.available_servants.discard(servant_name)
        
        logger.info(f"Servant confirmation: Successfully confirmed {servant_name} for {player_name}. "
                   f"Remaining available servants: {len(draft.available_servants)}")
        
        return True
    
    def get_players_needing_reselection(self, draft: Draft) -> List[int]:
        """Get list of player IDs who need to reselect due to conflicts"""
        reselect_users = []
        for servant, user_ids in draft.conflicted_servants.items():
            reselect_users.extend(user_ids)
        return reselect_users
    
    def is_servant_selection_complete(self, draft: Draft) -> bool:
        """Check if all non-captain players have confirmed servants with logging"""
        import logging
        logger = logging.getLogger(__name__)
        
        non_captain_players = [
            user_id for user_id, player in draft.players.items()
            if not player.is_captain
        ]
        
        confirmed_players = [
            user_id for user_id in non_captain_players
            if user_id in draft.confirmed_servants
        ]
        
        is_complete = len(confirmed_players) == len(non_captain_players)
        
        logger.info(
            f"Servant selection completion check: {len(confirmed_players)}/{len(non_captain_players)} "
            f"non-captain players have confirmed servants. Complete: {is_complete}"
        )
        
        if not is_complete:
            pending_players = [
                user_id for user_id in non_captain_players
                if user_id not in draft.confirmed_servants
            ]
            pending_names = [
                next((p.username for p in draft.players.values() if p.user_id == uid), f"User{uid}")
                for uid in pending_players
            ]
            logger.info(f"Servant selection: Players still pending confirmation: {', '.join(pending_names)}")
        
        return is_complete
    
    # =====================
    # Captain Ban Logic
    # =====================
    
    def initialize_captain_bans(self, draft: Draft) -> None:
        """Initialize captain ban phase after system bans and dice roll"""
        # Initialize ban progress tracking
        for captain_id in draft.captains:
            draft.captain_ban_progress[captain_id] = False
        
        # Set current banning captain to first in ban order
        if draft.captain_ban_order:
            draft.current_banning_captain = draft.captain_ban_order[0]
    
    def can_captain_ban(self, draft: Draft, captain_id: int) -> bool:
        """Check if a captain can make a ban"""
        return (
            captain_id == draft.current_banning_captain and
            not draft.captain_ban_progress.get(captain_id, False)
        )
    
    def apply_captain_ban(self, draft: Draft, captain_id: int, servant_name: str) -> bool:
        """
        Apply a captain ban and advance turn if needed.
        
        Returns:
            True if ban applied successfully
        """
        if not self.can_captain_ban(draft, captain_id):
            return False
        
        if not self.is_servant_available(draft, servant_name):
            return False
        
        # Apply the ban
        success = self.ban_servant(draft, servant_name, captain_id)
        if not success:
            return False
        
        # Mark captain as completed
        draft.captain_ban_progress[captain_id] = True
        
        # Advance to next captain or complete ban phase
        self._advance_captain_ban_turn(draft)
        
        return True
    
    def _advance_captain_ban_turn(self, draft: Draft) -> None:
        """Advance to next captain's turn or complete bans if all done"""
        current_captain = draft.current_banning_captain
        
        if not draft.captain_ban_progress.get(current_captain, False):
            return  # Current captain hasn't finished yet
        
        # Find next captain in order
        try:
            current_index = draft.captain_ban_order.index(current_captain)
            if current_index + 1 < len(draft.captain_ban_order):
                # Move to next captain
                draft.current_banning_captain = draft.captain_ban_order[current_index + 1]
            else:
                # All captains completed - clear current banning captain
                draft.current_banning_captain = None
        except ValueError:
            # Current captain not in ban order
            draft.current_banning_captain = None
    
    def are_captain_bans_complete(self, draft: Draft) -> bool:
        """Check if all captains have completed their bans"""
        return all(
            draft.captain_ban_progress.get(captain_id, False)
            for captain_id in draft.captains
        )
    
    def get_captain_ban_progress(self, draft: Draft) -> Dict[int, bool]:
        """Get captain ban progress status"""
        return {
            captain_id: draft.captain_ban_progress.get(captain_id, False)
            for captain_id in draft.captains
        }
