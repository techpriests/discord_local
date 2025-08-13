#!/usr/bin/env python3
"""
Aggregate independent simulation runs to find consensus-balanced rosters.

Usage:
  python scripts/aggregate_similar_rosters.py --guild <id> [--session <session_id>]

If --session is provided, only consider records with matching sim_session.
Otherwise, group by team_size and treat all sim_balanced records as candidates.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


DATA_FILE = Path("data/drafts/records.jsonl")


def read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    if not path.exists():
        return rows
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


def canonical_team_key(team: List[Dict]) -> Tuple[int, ...]:
    # sort by user_id to canonicalize
    ids = sorted(int(p.get("user_id")) for p in team)
    return tuple(ids)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--guild", type=int, required=True)
    parser.add_argument("--session", type=str, default=None)
    args = parser.parse_args()

    rows = read_jsonl(DATA_FILE)
    sims = [r for r in rows if r.get("mode") == "sim_balanced" and int(r.get("guild_id", 0)) == args.guild]
    if args.session:
        sims = [r for r in sims if r.get("sim_session") == args.session]

    # Count identical team1/team2 sets irrespective of ordering between teams
    # We canonicalize each roster by sorting team ids and then sorting tuple(team1_key, team2_key)
    counts = Counter()
    buckets = defaultdict(list)
    for r in sims:
        t1 = canonical_team_key(r.get("team1", []))
        t2 = canonical_team_key(r.get("team2", []))
        key = tuple(sorted([t1, t2]))
        counts[key] += 1
        buckets[key].append(r)

    print(f"Found {len(sims)} simulation records; {len(counts)} unique roster splits.")
    for key, cnt in counts.most_common(10):
        t1, t2 = key
        print(f"Count={cnt} | Team1={list(t1)} | Team2={list(t2)}")


if __name__ == "__main__":
    main()


