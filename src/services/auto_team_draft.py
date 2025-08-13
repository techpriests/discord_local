import random
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class PlayerInput:
    """Lightweight representation of a player for auto draft.

    This type intentionally avoids discord.py types so the service layer
    stays independent from Discord runtime objects.
    """
    user_id: int
    display_name: str
    rating: Optional[float] = None  # Optional skill rating if available


@dataclass
class AutoDraftResult:
    """Result of an automatic team draft operation."""
    team_one: List[PlayerInput]
    team_two: List[PlayerInput]
    extras: List[PlayerInput]


class AutoTeamDraftService:
    """Service that generates two teams automatically from a player pool.

    The service exposes a single main API: assign_teams. It tries to produce
    balanced teams when ratings are provided; otherwise it randomizes.
    """

    def __init__(self, random_seed: Optional[int] = None) -> None:
        self._random = random.Random(random_seed)

    def assign_teams(
        self,
        players: List[PlayerInput],
        team_size: int,
        *,
        balance_by_rating: bool = True,
    ) -> AutoDraftResult:
        """Assign players into two teams automatically.

        Args:
            players: Pool of players to split into teams
            team_size: Number of players per team
            balance_by_rating: Whether to try to balance by rating

        Returns:
            AutoDraftResult: Two teams and any extras left over

        Raises:
            ValueError: If team_size is invalid
        """
        if team_size <= 0:
            raise ValueError("team_size must be positive")

        max_players = team_size * 2
        if not players:
            return AutoDraftResult(team_one=[], team_two=[], extras=[])

        # If there are more players than needed, keep extras aside (stable/random selection)
        working_players = players.copy()
        self._random.shuffle(working_players)
        selected = working_players[:max_players]
        extras = working_players[max_players:]

        # If ratings exist and balancing is requested, do a simple greedy balance:
        # - Sort by rating descending (None treated as average)
        # - Assign each next highest rated to the team with smaller current total rating
        if balance_by_rating and any(p.rating is not None for p in selected):
            average = self._average_rating(selected)
            sorted_players = sorted(
                selected,
                key=lambda p: (p.rating if p.rating is not None else average),
                reverse=True,
            )

            team_one: List[PlayerInput] = []
            team_two: List[PlayerInput] = []
            sum_one = 0.0
            sum_two = 0.0

            for p in sorted_players:
                pr = p.rating if p.rating is not None else average
                # Respect team_size constraints while balancing
                if len(team_one) >= team_size:
                    team_two.append(p)
                    sum_two += pr
                elif len(team_two) >= team_size:
                    team_one.append(p)
                    sum_one += pr
                elif sum_one <= sum_two:
                    team_one.append(p)
                    sum_one += pr
                else:
                    team_two.append(p)
                    sum_two += pr

            return AutoDraftResult(team_one=team_one, team_two=team_two, extras=extras)

        # Fallback: random split respecting team_size
        team_one = selected[:team_size]
        team_two = selected[team_size:team_size * 2]
        return AutoDraftResult(team_one=team_one, team_two=team_two, extras=extras)

    def _average_rating(self, players: List[PlayerInput]) -> float:
        ratings = [p.rating for p in players if p.rating is not None]
        if not ratings:
            return 0.0
        return sum(ratings) / float(len(ratings))

    # Placeholder for ML-based balancing. When a predictor is available, callers
    # can pass a callback that scores a split; this method can be extended to
    # use local search to approach a 50/50 predicted win probability.
    def assign_with_predictor(
        self,
        players: List[PlayerInput],
        team_size: int,
        score_split: Optional[callable] = None,
        attempts: int = 64,
    ) -> AutoDraftResult:
        if score_split is None:
            return self.assign_teams(players, team_size, balance_by_rating=True)

        max_players = team_size * 2
        working_players = players.copy()
        self._random.shuffle(working_players)
        selected = working_players[:max_players]
        extras = working_players[max_players:]

        best_split: Optional[Tuple[List[PlayerInput], List[PlayerInput]]] = None
        best_score = float("inf")

        for _ in range(attempts):
            self._random.shuffle(selected)
            team_one = selected[:team_size]
            team_two = selected[team_size:team_size * 2]
            score = abs(score_split(team_one, team_two) - 0.5)
            if score < best_score:
                best_score = score
                best_split = (team_one[:], team_two[:])

        if best_split is None:
            return self.assign_teams(players, team_size, balance_by_rating=True)

        return AutoDraftResult(team_one=best_split[0], team_two=best_split[1], extras=extras)


