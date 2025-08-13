from __future__ import annotations

from typing import Dict, Iterable

from .auto_predictor import TeamPlayer


def build_features(team1: Iterable[TeamPlayer], team2: Iterable[TeamPlayer]) -> Dict[str, float]:
    """Create simple dict features from two teams.

    Features include:
      - sum_rating_team1, sum_rating_team2, diff_rating
      - counts per servant per team (servant:헤클_team1, servant:헤클_team2)
    """
    f: Dict[str, float] = {}

    def add(prefix: str, team: Iterable[TeamPlayer]) -> float:
        total = 0.0
        for p in team:
            if p.rating is not None:
                total += p.rating
            if p.servant:
                key = f"servant:{p.servant}_{prefix}"
                f[key] = f.get(key, 0.0) + 1.0
        f[f"sum_rating_{prefix}"] = total
        return total

    s1 = add("team1", team1)
    s2 = add("team2", team2)
    f["diff_rating"] = s1 - s2
    return f


