import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class RosterPlayer:
    user_id: int
    display_name: str
    rating: Optional[float] = None
    servant_ratings: Dict[str, float] = field(default_factory=dict)


class RosterStore:
    """Persistent roster per guild for simulations and rating metadata."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        base = Path(base_dir or "data")
        self.dir = base / "rosters"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, guild_id: int) -> Path:
        return self.dir / f"{guild_id}.json"

    def load(self, guild_id: int) -> List[RosterPlayer]:
        path = self._path(guild_id)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        players: List[RosterPlayer] = []
        for item in data.get("players", []):
            players.append(
                RosterPlayer(
                    user_id=int(item["user_id"]),
                    display_name=item.get("display_name", str(item["user_id"])),
                    rating=item.get("rating"),
                    servant_ratings=item.get("servant_ratings", {}),
                )
            )
        return players

    def save(self, guild_id: int, players: List[RosterPlayer]) -> None:
        path = self._path(guild_id)
        payload = {"players": [asdict(p) for p in players]}
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def add_or_update(self, guild_id: int, new_players: List[RosterPlayer]) -> None:
        current = {p.user_id: p for p in self.load(guild_id)}
        for p in new_players:
            current[p.user_id] = p
        self.save(guild_id, list(current.values()))

    def remove(self, guild_id: int, user_ids: List[int]) -> None:
        players = [p for p in self.load(guild_id) if p.user_id not in set(user_ids)]
        self.save(guild_id, players)

    def set_rating(self, guild_id: int, user_id: int, rating: Optional[float]) -> None:
        players = self.load(guild_id)
        for p in players:
            if p.user_id == user_id:
                p.rating = rating
                break
        else:
            players.append(RosterPlayer(user_id=user_id, display_name=str(user_id), rating=rating))
        self.save(guild_id, players)

    def set_servant_rating(self, guild_id: int, user_id: int, servant: str, rating: Optional[float]) -> None:
        players = self.load(guild_id)
        for p in players:
            if p.user_id == user_id:
                if rating is None:
                    p.servant_ratings.pop(servant, None)
                else:
                    p.servant_ratings[servant] = rating
                break
        else:
            rp = RosterPlayer(user_id=user_id, display_name=str(user_id))
            if rating is not None:
                rp.servant_ratings[servant] = rating
            players.append(rp)
        self.save(guild_id, players)


