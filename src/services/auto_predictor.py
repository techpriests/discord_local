from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Dict
import json
import math
from pathlib import Path


@dataclass
class TeamPlayer:
    user_id: int
    display_name: str
    servant: Optional[str] = None
    rating: Optional[float] = None
    is_captain: bool = False


class DraftOutcomePredictor:
    """Stub predictor that estimates P(team1 wins).

    Start with a heuristic: sum of ratings. Later, load an ML model
    trained from `data/drafts/records.jsonl`.
    """

    def __init__(self) -> None:
        self.is_trained = False
        self.model_path = Path("data/models/auto_predictor.json")
        self.coef_: Dict[str, float] = {}
        self.bias_: float = 0.0

    def load_or_train(self) -> None:
        # Load a simple JSON model if available (coef dict + bias)
        try:
            if self.model_path.exists():
                with self.model_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                self.coef_ = data.get("coef", {})
                self.bias_ = float(data.get("bias", 0.0))
                self.is_trained = True
            else:
                self.is_trained = False
        except Exception:
            self.is_trained = False

    def predict_team1_win_prob(
        self,
        team1: Iterable[TeamPlayer],
        team2: Iterable[TeamPlayer],
    ) -> float:
        # Simple heuristic fallback: normalize sum of ratings
        def sum_rating(team: Iterable[TeamPlayer]) -> float:
            total = 0.0
            count = 0
            for p in team:
                if p.rating is not None:
                    total += p.rating
                    count += 1
            # If no ratings, assume equal strength
            return total if count > 0 else 0.0

        s1 = sum_rating(team1)
        s2 = sum_rating(team2)
        if s1 == 0.0 and s2 == 0.0:
            return 0.5
        # Map difference to probability using a logistic-like transform
        diff = s1 - s2
        heuristic = 1.0 / (1.0 + math.exp(-diff / 10.0))

        if not self.is_trained or not self.coef_:
            return heuristic

        # If trained, use linear logit with features
        from .predictor_features import build_features
        feats = build_features(team1, team2)
        logit = self.bias_
        for k, v in feats.items():
            logit += self.coef_.get(k, 0.0) * float(v)
        return 1.0 / (1.0 + math.exp(-logit))


