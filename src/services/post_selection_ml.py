import json
import os
from typing import List, Dict, Any

import numpy as np

from src.services.match_recorder import MatchRecorder, PlayerFeature
from src.services.roster_store import RosterStore
from src.commands.auto_balance import (
    SelectedPlayer,
    PostSelectionFeatures,
    PostSelectionTeamBalancer,
)


class PostSelectionMLTrainer:
    def __init__(self, match_recorder: MatchRecorder, roster_store: RosterStore) -> None:
        self.match_recorder = match_recorder
        self.roster_store = roster_store

    def train_balance_predictor_from_existing_data(self) -> Dict[str, Any]:
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import train_test_split, cross_val_score
            import joblib
        except Exception as e:
            return {"success": False, "error": f"Missing ML dependencies: {e}"}

        matches = self.match_recorder.load_all_matches()
        if len(matches) < 30:
            return {"success": False, "error": "Insufficient match data (need >= 30)"}

        X_train: List[List[float]] = []
        y_train: List[int] = []

        for match in matches:
            try:
                team1_selected = self._convert_match_team_to_selected_players(match.team1, match.guild_id)
                team2_selected = self._convert_match_team_to_selected_players(match.team2, match.guild_id)
                balancer = PostSelectionTeamBalancer(self.roster_store)
                team1_features = balancer._extract_team_features(team1_selected)
                team2_features = balancer._extract_team_features(team2_selected)
                feature_vector = self._create_comparative_feature_vector(team1_features, team2_features)
                X_train.append(feature_vector)
                y_train.append(1 if match.winner == 1 else 0)
            except Exception:
                continue

        if len(X_train) < 20:
            return {"success": False, "error": "Too few valid training samples"}

        X = np.array(X_train)
        y = np.array(y_train)
        X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        cv_scores = cross_val_score(model, X_tr, y_tr, cv=5)
        model.fit(X_tr, y_tr)
        val_accuracy = float(model.score(X_val, y_val))

        os.makedirs('models', exist_ok=True)
        joblib.dump(model, 'models/post_selection_balance_predictor.pkl')
        return {"success": True, "cv_mean": float(np.mean(cv_scores)), "cv_std": float(np.std(cv_scores)), "val_accuracy": val_accuracy}

    def _convert_match_team_to_selected_players(self, team_data: List[PlayerFeature], guild_id: int) -> List[SelectedPlayer]:
        selected_players: List[SelectedPlayer] = []
        for pf in team_data:
            skill_rating = pf.rating
            if skill_rating is None:
                try:
                    roster = self.roster_store.load(guild_id)
                    rp = next((p for p in roster if p.user_id == pf.user_id), None)
                    if rp:
                        skill_rating = rp.rating
                except Exception:
                    skill_rating = 1000.0
            selected_players.append(SelectedPlayer(
                user_id=pf.user_id,
                display_name=pf.display_name,
                selected_character=pf.servant or "unknown",
                skill_rating=skill_rating,
                character_proficiency=None,
            ))
        return selected_players

    def _create_comparative_feature_vector(self, t1: PostSelectionFeatures, t2: PostSelectionFeatures) -> List[float]:
        return [
            t1.avg_skill_rating - t2.avg_skill_rating,
            abs(t1.skill_variance - t2.skill_variance),
            t1.team_synergy_score - t2.team_synergy_score,
            t1.meta_strength_score - t2.meta_strength_score,
            len(t1.role_coverage) - len(t2.role_coverage),
            t1.detection_vs_stealth_balance - t2.detection_vs_stealth_balance,
            t1.character_comfort_avg - t2.character_comfort_avg,
        ]

    def learn_character_synergies_from_matches(self) -> Dict[str, Any]:
        matches = self.match_recorder.load_all_matches()
        synergy_data: Dict[tuple, Dict[str, int]] = {}
        for match in matches:
            winning = match.team1 if match.winner == 1 else match.team2
            losing = match.team2 if match.winner == 1 else match.team1
            win_chars = [p.servant for p in winning if p.servant]
            lose_chars = [p.servant for p in losing if p.servant]
            for i, c1 in enumerate(win_chars):
                for c2 in win_chars[i + 1:]:
                    k = tuple(sorted((c1, c2)))
                    synergy_data.setdefault(k, {"wins": 0, "total": 0})
                    synergy_data[k]["wins"] += 1
                    synergy_data[k]["total"] += 1
            for i, c1 in enumerate(lose_chars):
                for c2 in lose_chars[i + 1:]:
                    k = tuple(sorted((c1, c2)))
                    synergy_data.setdefault(k, {"wins": 0, "total": 0})
                    synergy_data[k]["total"] += 1

        synergy_matrix: Dict[str, float] = {}
        for (c1, c2), stats in synergy_data.items():
            if stats['total'] >= 3:
                winrate = stats['wins'] / stats['total']
                synergy_score = (winrate - 0.5) * 2
                synergy_matrix[f"{c1}|{c2}"] = synergy_score

        os.makedirs('data', exist_ok=True)
        with open('data/character_synergies.json', 'w', encoding='utf-8') as f:
            json.dump(synergy_matrix, f, ensure_ascii=False, indent=2)
        return {"success": True, "pairs": len(synergy_matrix), "matches": len(matches)}


