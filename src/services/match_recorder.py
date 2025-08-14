import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class PlayerFeature:
    user_id: int
    display_name: str
    rating: Optional[float] = None
    servant: Optional[str] = None
    is_captain: bool = False
    pick_order: Optional[int] = None


@dataclass
class MatchRecord:
    match_id: str
    timestamp: float
    guild_id: int
    channel_id: int
    team_size: int
    captains: List[int]
    team1: List[PlayerFeature]
    team2: List[PlayerFeature]
    bans: List[str]
    map: Optional[str] = None
    mode: Optional[str] = None
    winner: Optional[int] = None  # 1 or 2
    score: Optional[str] = None
    sim_session: Optional[str] = None
    author_id: Optional[int] = None
    is_simulation: Optional[bool] = None
    sim_author_captain: Optional[int] = None
    sim_note: Optional[str] = None
    # AI/Auto-balance metadata
    draft_type: Optional[str] = None  # 'manual' | 'auto' | 'simulation'
    balance_algorithm: Optional[str] = None
    predicted_balance_score: Optional[float] = None
    predicted_confidence: Optional[float] = None
    processing_time: Optional[float] = None
    auto_balance_used: Optional[bool] = None


class MatchRecorder:
    """Append-only JSONL recorder for draft matches and outcomes."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = base_dir or os.getenv("MUMU_DATA_DIR", "data")
        self.records_dir = Path(self.base_dir) / "drafts"
        self.records_file = self.records_dir / "records.jsonl"
        self.records_dir.mkdir(parents=True, exist_ok=True)

    def write_prematch(
        self,
        match_id: str,
        guild_id: int,
        channel_id: int,
        team_size: int,
        captains: List[int],
        team1: List[PlayerFeature],
        team2: List[PlayerFeature],
        bans: List[str],
        map_name: Optional[str] = None,
        mode_name: Optional[str] = None,
        sim_session: Optional[str] = None,
        author_id: Optional[int] = None,
        is_simulation: Optional[bool] = None,
        sim_author_captain: Optional[int] = None,
        sim_note: Optional[str] = None,
    ) -> MatchRecord:
        record = MatchRecord(
            match_id=match_id,
            timestamp=time.time(),
            guild_id=guild_id,
            channel_id=channel_id,
            team_size=team_size,
            captains=captains,
            team1=team1,
            team2=team2,
            bans=bans,
            map=map_name,
            mode=mode_name,
            sim_session=sim_session,
            author_id=author_id,
            is_simulation=is_simulation,
            sim_author_captain=sim_author_captain,
            sim_note=sim_note,
        )
        self._append_record(record)
        return record

    def write_outcome(
        self,
        match_id: str,
        winner: int,
        score: Optional[str] = None,
    ) -> None:
        # For append-only, we write a small outcome patch entry with same match_id
        score_team1: Optional[int] = None
        score_team2: Optional[int] = None
        score_margin: Optional[int] = None
        if isinstance(score, str):
            try:
                parts = score.replace('：', ':').split(':')
                if len(parts) == 2:
                    a = int(parts[0].strip())
                    b = int(parts[1].strip())
                    score_team1 = a
                    score_team2 = b
                    score_margin = abs(a - b)
            except Exception:
                pass
        patch = {
            "match_id": match_id,
            "timestamp": time.time(),
            "outcome": {
                "winner": winner,
                "score": score,
                "score_team1": score_team1,
                "score_team2": score_team2,
                "score_margin": score_margin,
            },
        }
        with self.records_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(patch, ensure_ascii=False) + "\n")

    def _append_record(self, record: MatchRecord) -> None:
        payload = asdict(record)
        # Convert nested dataclasses to dicts
        payload["team1"] = [asdict(p) for p in record.team1]
        payload["team2"] = [asdict(p) for p in record.team2]
        with self.records_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


