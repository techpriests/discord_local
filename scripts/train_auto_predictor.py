#!/usr/bin/env python3
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression


DATA_FILE = Path("data/drafts/records.jsonl")
MODEL_DIR = Path("data/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
PICKLE_PATH = MODEL_DIR / "auto_predictor.pkl"
JSON_PATH = MODEL_DIR / "auto_predictor.json"


@dataclass
class Player:
    user_id: int
    display_name: str
    rating: Optional[float]
    servant: Optional[str]
    is_captain: bool


def read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def split_prematch_and_outcomes(rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    prematches: List[Dict] = []
    outcomes: List[Dict] = []
    for r in rows:
        if "team1" in r and "team2" in r:
            prematches.append(r)
        elif "outcome" in r and "match_id" in r:
            outcomes.append(r)
    return prematches, outcomes


def latest_outcome_for_channel(outcomes: List[Dict], guild_id: int, channel_id: int) -> Optional[Dict]:
    prefix = f"{guild_id}:{channel_id}:"
    filtered = [o for o in outcomes if str(o.get("match_id", "")).startswith(prefix)]
    if not filtered:
        return None
    return sorted(filtered, key=lambda x: x.get("timestamp", 0))[-1]


def extract_players(team: List[Dict]) -> List[Player]:
    players: List[Player] = []
    for p in team:
        players.append(
            Player(
                user_id=int(p.get("user_id")),
                display_name=p.get("display_name", str(p.get("user_id"))),
                rating=p.get("rating"),
                servant=p.get("servant"),
                is_captain=bool(p.get("is_captain", False)),
            )
        )
    return players


def build_features(team1: List[Player], team2: List[Player]) -> Dict[str, float]:
    feats: Dict[str, float] = {}

    def add(prefix: str, team: List[Player]) -> float:
        total = 0.0
        for p in team:
            if p.rating is not None:
                total += float(p.rating)
            if p.servant:
                key = f"servant:{p.servant}_{prefix}"
                feats[key] = feats.get(key, 0.0) + 1.0
        feats[f"sum_rating_{prefix}"] = total
        return total

    s1 = add("team1", team1)
    s2 = add("team2", team2)
    feats["diff_rating"] = s1 - s2
    return feats


def vectorize(feature_dicts: List[Dict[str, float]]) -> Tuple[np.ndarray, List[str]]:
    # Collect all feature keys
    keys: List[str] = sorted({k for fd in feature_dicts for k in fd.keys()})
    X = np.zeros((len(feature_dicts), len(keys)), dtype=float)
    for i, fd in enumerate(feature_dicts):
        for j, k in enumerate(keys):
            X[i, j] = float(fd.get(k, 0.0))
    return X, keys


def main() -> None:
    rows = read_jsonl(DATA_FILE)
    prematches, outcomes = split_prematch_and_outcomes(rows)

    X_feats: List[Dict[str, float]] = []
    y: List[int] = []

    for pm in prematches:
        guild_id = int(pm.get("guild_id", 0))
        channel_id = int(pm.get("channel_id", 0))
        team1 = extract_players(pm.get("team1", []))
        team2 = extract_players(pm.get("team2", []))
        feat = build_features(team1, team2)

        out = latest_outcome_for_channel(outcomes, guild_id, channel_id)
        if out and "outcome" in out and isinstance(out["outcome"], dict) and out["outcome"].get("winner") in (1, 2):
            X_feats.append(feat)
            y.append(1 if out["outcome"]["winner"] == 1 else 0)

    if not X_feats:
        print("No training data found. Exiting.")
        return

    X, keys = vectorize(X_feats)
    y_arr = np.array(y, dtype=int)

    # Train logistic regression with balanced class weights
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X, y_arr)

    # Save pickle
    joblib.dump({"model": model, "keys": keys}, PICKLE_PATH)

    # Also save lightweight JSON for runtime predictor
    coef_map = {k: float(w) for k, w in zip(keys, model.coef_[0].tolist())}
    data = {"coef": coef_map, "bias": float(model.intercept_[0])}
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Saved model to {PICKLE_PATH} and {JSON_PATH}")


if __name__ == "__main__":
    main()


