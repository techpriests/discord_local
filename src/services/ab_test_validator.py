import time
from typing import List, Dict, Any

import numpy as np

from src.commands.auto_balance import SelectedPlayer, TeamBalanceRequest, PostSelectionTeamBalancer


class PostSelectionABTester:
    def __init__(self, balancer: PostSelectionTeamBalancer) -> None:
        self.balancer = balancer

    def test_algorithm_performance(self, character_selections: List[SelectedPlayer], team_size: int, iterations: int = 50) -> Dict[str, Any]:
        algorithms = ['genetic', 'monte_carlo', 'simple']
        results = {}
        for algo in algorithms:
            scores = []
            times = []
            for _ in range(iterations):
                start = time.time()
                req = TeamBalanceRequest(players=character_selections, team_size=team_size, balance_algorithm=algo)
                res = self.balancer.balance_teams(req)
                times.append(time.time() - start)
                scores.append(res.balance_score)
            results[algo] = {
                'avg_balance_score': float(np.mean(scores)) if scores else 0.0,
                'std_balance_score': float(np.std(scores)) if scores else 0.0,
                'avg_processing_time': float(np.mean(times)) if times else 0.0,
                'consistency': float(1.0 - np.std(scores)) if scores else 0.0,
                'efficiency': float(1.0 / np.mean(times)) if times else 0.0,
            }
        return results


class PostSelectionValidator:
    def __init__(self, balancer: PostSelectionTeamBalancer) -> None:
        self.balancer = balancer

    def validate_balance_constraints(self, result) -> Dict[str, bool]:
        validations = {
            'equal_team_sizes': len(result.team1) == len(result.team2),
            'no_duplicate_players': len({p.user_id for p in result.team1 + result.team2}) == len(result.team1) + len(result.team2),
            'all_characters_assigned': all(p.selected_character for p in result.team1 + result.team2),
            'balance_score_valid': 0.0 <= result.balance_score <= 1.0,
            'confidence_valid': 0.0 <= result.confidence <= 1.0,
        }
        return validations

    def test_edge_cases(self) -> Dict[str, Any]:
        players = [SelectedPlayer(user_id=i, display_name=f"Player{i}", selected_character="세이버", skill_rating=1000.0) for i in range(6)]
        req = TeamBalanceRequest(players=players, team_size=3)
        result = self.balancer.balance_teams(req)
        return {
            'balance_score': result.balance_score,
            'passes': result.balance_score > 0.9,
            'team1_size': len(result.team1),
            'team2_size': len(result.team2),
        }


