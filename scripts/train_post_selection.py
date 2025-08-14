#!/usr/bin/env python
import sys
import asyncio

from src.services.match_recorder import MatchRecorder
from src.services.roster_store import RosterStore
from src.services.post_selection_ml import PostSelectionMLTrainer


async def main() -> int:
    match_recorder = MatchRecorder()
    roster_store = RosterStore()
    trainer = PostSelectionMLTrainer(match_recorder, roster_store)

    print("[1/2] Learning character synergies from matches...")
    res1 = trainer.learn_character_synergies_from_matches()
    print(res1)

    print("[2/2] Training balance predictor from existing data...")
    res2 = trainer.train_balance_predictor_from_existing_data()
    print(res2)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))


