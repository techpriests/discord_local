from typing import Dict, Any


class AutoBalanceConfig:
    def __init__(self, guild_id: int | None = None) -> None:
        self.guild_id = guild_id or 0
        self.enabled = True
        self.default_algorithm = 'genetic'
        self.balance_weights: Dict[str, float] = {
            'skill_balance': 0.30,
            'synergy_balance': 0.25,
            'role_balance': 0.20,
            'tier_balance': 0.10,
            'comfort_balance': 0.10,
            'meta_balance': 0.05,
        }
        self.algorithm_settings: Dict[str, Dict[str, Any]] = {
            'genetic': {
                'population_size': 50,
                'generations': 100,
                'mutation_rate': 0.1,
                'crossover_rate': 0.8,
            },
            'monte_carlo': {
                'iterations': 1000,
                'temperature': 0.1,
            },
            'simple': {},
        }

    def update_balance_weights(self, new_weights: Dict[str, float]) -> None:
        total = sum(new_weights.values())
        if abs(total - 1.0) > 0.02:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        for k, v in new_weights.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"Weight {k} must be between 0.0 and 1.0")
        self.balance_weights.update(new_weights)

    def set_default_algorithm(self, algorithm: str) -> None:
        if algorithm not in ['genetic', 'monte_carlo', 'simple']:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        self.default_algorithm = algorithm


