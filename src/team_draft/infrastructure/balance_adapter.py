"""
Balance Calculator Adapter

Adapter for auto-balance service integration.
Preserves existing auto-balance functionality.
"""

from typing import Dict, Any, Optional, List
from ..application.interfaces import IBalanceCalculator
from ..domain.entities.draft import Draft
from src.services.auto_balance_config import AutoBalanceConfig
from src.commands.auto_balance import PostSelectionTeamBalancer


class AutoBalanceAdapter(IBalanceCalculator):
    """
    Adapter for existing auto-balance system.
    
    Wraps the existing auto-balance services to work with new architecture.
    """
    
    def __init__(self):
        self._config = AutoBalanceConfig()
        # Initialize balancer with required roster_store
        from src.services.roster_store import RosterStore
        roster_store = RosterStore()
        self._balancer = PostSelectionTeamBalancer(roster_store)
    
    async def calculate_team_balance(self, draft: Draft) -> Dict[str, Any]:
        """Calculate team balance and return analysis"""
        if draft.phase.value not in ["team_selection", "completed"]:
            return {"error": "Team balance can only be calculated during/after team selection"}
        
        try:
            # Convert draft to format expected by existing auto-balance system
            team_data = self._convert_draft_to_balance_format(draft)
            
            # Use existing balance calculation logic
            balance_score = self._calculate_balance_score(team_data)
            
            return {
                "balance_score": balance_score,
                "team1_strength": team_data.get("team1_strength", 0),
                "team2_strength": team_data.get("team2_strength", 0),
                "recommendations": self._get_balance_recommendations(draft, team_data)
            }
            
        except Exception as e:
            return {"error": f"Balance calculation failed: {str(e)}"}
    
    async def auto_balance_teams(self, draft: Draft, algorithm: str) -> Dict[str, Any]:
        """Perform automatic team balancing using specified algorithm"""
        if draft.phase.value not in ["servant_selection", "servant_reselection", "team_selection"]:
            return {"error": "Auto-balance can only be performed during servant selection or team selection"}
        
        try:
            # Convert draft to format expected by existing system
            balance_input = self._convert_draft_to_balance_input(draft)
            
            # Use existing auto-balance logic
            balance_result = await self._balancer.balance_teams(
                players=balance_input["players"],
                algorithm=algorithm,
                team_size=draft.team_size
            )
            
            # Convert result back to our format
            return {
                "algorithm": algorithm,
                "success": balance_result.get("success", False),
                "teams": balance_result.get("teams", {}),
                "balance_score": balance_result.get("balance_score", 0),
                "confidence": balance_result.get("confidence", 0),
                "reasoning": balance_result.get("reasoning", ""),
                "processing_time": balance_result.get("processing_time", 0)
            }
            
        except Exception as e:
            return {
                "algorithm": algorithm,
                "success": False,
                "error": f"Auto-balance failed: {str(e)}"
            }
    
    def _convert_draft_to_balance_format(self, draft: Draft) -> Dict[str, Any]:
        """Convert draft to format expected by balance calculator"""
        team1_players = []
        team2_players = []
        
        for player in draft.players.values():
            player_data = {
                "user_id": player.user_id,
                "username": player.username,
                "servant": player.selected_servant,
                "is_captain": player.is_captain
            }
            
            if player.team == 1:
                team1_players.append(player_data)
            elif player.team == 2:
                team2_players.append(player_data)
        
        return {
            "team1": team1_players,
            "team2": team2_players,
            "team1_strength": self._calculate_team_strength(team1_players, draft),
            "team2_strength": self._calculate_team_strength(team2_players, draft),
            "draft_info": {
                "team_size": draft.team_size,
                "guild_id": draft.guild_id,
                "channel_id": draft.channel_id
            }
        }
    
    def _convert_draft_to_balance_input(self, draft: Draft) -> Dict[str, Any]:
        """Convert draft to format expected by auto-balance system"""
        players = []
        
        for player in draft.players.values():
            player_data = {
                "user_id": player.user_id,
                "display_name": player.username,
                "servant": player.selected_servant,
                "is_captain": player.is_captain,
                "rating": None  # Could be enhanced with rating system
            }
            players.append(player_data)
        
        return {
            "players": players,
            "captains": draft.captains.copy(),
            "banned_servants": list(draft.banned_servants),
            "available_servants": list(draft.get_available_servants()),
            "servant_categories": dict(draft.servant_categories),
            "draft_metadata": {
                "guild_id": draft.guild_id,
                "channel_id": draft.channel_id,
                "team_size": draft.team_size,
                "is_test_mode": draft.is_test_mode
            }
        }
    
    def _calculate_team_strength(self, team_players: list, draft: Draft) -> float:
        """Calculate team strength based on servant composition"""
        if not team_players:
            return 0.0
        
        strength = 0.0
        
        # Basic strength calculation based on servant tiers
        for player in team_players:
            servant = player.get("servant")
            if not servant:
                continue
            
            # Tier-based scoring (preserves existing logic)
            if servant in draft.servant_tiers.get("S", []):
                strength += 1.0
            elif servant in draft.servant_tiers.get("A", []):
                strength += 0.8
            elif servant in draft.servant_tiers.get("B", []):
                strength += 0.6
            else:
                strength += 0.4
            
            # Special ability bonuses
            if servant in draft.detection_servants:
                strength += 0.2
            if servant in draft.cloaking_servants:
                strength += 0.1
        
        return strength
    
    def _calculate_balance_score(self, team_data: Dict[str, Any]) -> float:
        """Calculate balance score between teams"""
        team1_strength = team_data.get("team1_strength", 0)
        team2_strength = team_data.get("team2_strength", 0)
        
        if team1_strength == 0 and team2_strength == 0:
            return 1.0  # Perfect balance if no data
        
        total_strength = team1_strength + team2_strength
        if total_strength == 0:
            return 1.0
        
        # Calculate balance as 1 - abs(difference) / total
        difference = abs(team1_strength - team2_strength)
        balance_score = 1.0 - (difference / total_strength)
        
        return max(0.0, min(1.0, balance_score))
    
    def _get_balance_recommendations(self, draft: Draft, team_data: Dict[str, Any]) -> List[str]:
        """Get recommendations for improving team balance"""
        recommendations = []
        
        team1_strength = team_data.get("team1_strength", 0)
        team2_strength = team_data.get("team2_strength", 0)
        
        if abs(team1_strength - team2_strength) > 0.5:
            stronger_team = 1 if team1_strength > team2_strength else 2
            weaker_team = 2 if stronger_team == 1 else 1
            recommendations.append(f"Team {stronger_team} appears stronger than Team {weaker_team}")
        
        # Check for special ability imbalances
        team1_detection = sum(1 for p in team_data.get("team1", []) 
                             if p.get("servant") in draft.detection_servants)
        team2_detection = sum(1 for p in team_data.get("team2", []) 
                             if p.get("servant") in draft.detection_servants)
        
        if team1_detection > 0 and team2_detection == 0:
            recommendations.append("Team 1 has detection advantage")
        elif team2_detection > 0 and team1_detection == 0:
            recommendations.append("Team 2 has detection advantage")
        
        team1_cloaking = sum(1 for p in team_data.get("team1", []) 
                            if p.get("servant") in draft.cloaking_servants)
        team2_cloaking = sum(1 for p in team_data.get("team2", []) 
                            if p.get("servant") in draft.cloaking_servants)
        
        if abs(team1_cloaking - team2_cloaking) > 1:
            recommendations.append("Uneven cloaking ability distribution")
        
        return recommendations
