import discord
import numpy as np
import random
import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Any, TYPE_CHECKING, Set

from src.services.roster_store import RosterStore
if TYPE_CHECKING:
    # Only for type hints; avoids circular imports at runtime
    from src.commands.team_draft import DraftSession, TeamDraftCommands


# -------- Data Models --------

@dataclass
class SelectedPlayer:
    user_id: int
    display_name: str
    selected_character: Optional[str] = None
    skill_rating: Optional[float] = None
    character_proficiency: Optional[float] = None


@dataclass
class TeamBalanceRequest:
    players: List[SelectedPlayer]
    team_size: int
    balance_algorithm: str = "simple"


@dataclass
class TeamBalanceResult:
    team1: List[SelectedPlayer]
    team2: List[SelectedPlayer]
    extras: List[SelectedPlayer]
    balance_score: float
    confidence: float
    analysis: Dict[str, Any]
    alternative_arrangements: List[Tuple[List[SelectedPlayer], List[SelectedPlayer]]] = field(default_factory=list)
    algorithm: str = "simple"


@dataclass
class PostSelectionFeatures:
    avg_skill_rating: float = 0.0
    skill_variance: float = 0.0
    team_synergy_score: float = 0.0
    role_coverage: List[str] = field(default_factory=list)
    tier_distribution: Dict[str, int] = field(default_factory=dict)
    detection_vs_stealth_balance: float = 0.0
    meta_strength_score: float = 0.0
    character_comfort_avg: float = 0.0


# -------- Balancer --------

class PostSelectionTeamBalancer:
    """Minimal post-selection team balancer (Week 1 quick win).

    Balances teams primarily by player skill rating, using roster ratings when available.
    """

    def __init__(self, roster_store: RosterStore) -> None:
        self.roster_store = roster_store
        self._synergy: Dict[Tuple[str, str], float] = self._load_synergy()
        self._weights = {
            "skill_balance": 0.30,
            "synergy_balance": 0.25,
            "role_balance": 0.20,
            "tier_balance": 0.10,
            "comfort_balance": 0.10,
            "meta_balance": 0.05,
        }

    def balance_teams(self, request: TeamBalanceRequest) -> TeamBalanceResult:
        start = time.time()
        players = list(request.players)
        for p in players:
            if p.skill_rating is None:
                p.skill_rating = 1000.0

        if request.balance_algorithm == "genetic":
            result = self._balance_genetic(players, request.team_size)
        elif request.balance_algorithm == "monte_carlo":
            result = self._balance_monte_carlo(players, request.team_size)
        else:
            result = self._balance_simple(players, request.team_size)

        result.algorithm = request.balance_algorithm
        result.analysis["processing_time"] = time.time() - start
        return result

    def _balance_simple(self, players: List[SelectedPlayer], team_size: int) -> TeamBalanceResult:
        players = sorted(players, key=lambda p: p.skill_rating or 1000.0, reverse=True)
        team1: List[SelectedPlayer] = []
        team2: List[SelectedPlayer] = []
        extras: List[SelectedPlayer] = []
        for i, player in enumerate(players):
            if len(team1) >= team_size and len(team2) >= team_size:
                extras.append(player)
                continue
            target = team1 if (i % 2 == 0) else team2
            if len(target) < team_size:
                target.append(player)
            else:
                (team2 if target is team1 else team1).append(player)
        balance_score, analysis = self._evaluate_split(team1, team2)
        return TeamBalanceResult(team1=team1, team2=team2, extras=extras, balance_score=balance_score, confidence=self._confidence(balance_score), analysis=analysis)

    def _balance_monte_carlo(self, players: List[SelectedPlayer], team_size: int, iterations: int = 400) -> TeamBalanceResult:
        best = None
        best_score = -1.0
        top_candidates: List[Tuple[float, Tuple[List[SelectedPlayer], List[SelectedPlayer], List[SelectedPlayer]]]] = []
        for _ in range(iterations):
            shuffled = list(players)
            random.shuffle(shuffled)
            team1 = shuffled[:team_size]
            team2 = shuffled[team_size:team_size * 2]
            extras = shuffled[team_size * 2:]
            score, analysis = self._evaluate_split(team1, team2)
            if score > best_score:
                best_score = score
                best = (team1, team2, extras, analysis)
            top_candidates.append((score, (team1, team2, extras)))
        top_candidates.sort(key=lambda x: x[0], reverse=True)
        alternatives = []
        for _, (t1, t2, _ex) in top_candidates[1:4]:
            alternatives.append((list(t1), list(t2)))
        if best is None:
            return self._balance_simple(players, team_size)
        team1, team2, extras, analysis = best
        return TeamBalanceResult(team1=team1, team2=team2, extras=extras, balance_score=best_score, confidence=self._confidence(best_score), analysis=analysis, alternative_arrangements=alternatives)

    def _balance_genetic(self, players: List[SelectedPlayer], team_size: int, population_size: int = 30, generations: int = 50, mutation_rate: float = 0.1) -> TeamBalanceResult:
        n = len(players)
        indices = list(range(n))

        def make_individual() -> Tuple[Set[int], Set[int], Set[int]]:
            idx = indices.copy()
            random.shuffle(idx)
            t1_idx = set(idx[:team_size])
            t2_idx = set(idx[team_size:team_size * 2])
            ex_idx = set(idx[team_size * 2:])
            return t1_idx, t2_idx, ex_idx

        def crossover(a: Tuple[Set[int], Set[int], Set[int]], b: Tuple[Set[int], Set[int], Set[int]]):
            a1, a2, _ = a
            b1, b2, _ = b
            cut = random.randint(0, min(len(a1), len(b1)))
            child1_first = set(list(a1)[:cut] + list(b1)[cut:])
            child2_first = set(list(b1)[:cut] + list(a1)[cut:])
            def build(child_first: Set[int]) -> Tuple[Set[int], Set[int], Set[int]]:
                remaining = [i for i in indices if i not in child_first]
                t2 = set(remaining[:team_size])
                ex = set(remaining[team_size:])
                return child_first, t2, ex
            return build(child1_first), build(child2_first)

        def mutate(indv: Tuple[Set[int], Set[int], Set[int]]):
            t1, t2, ex = indv
            if random.random() < mutation_rate and t1 and t2:
                i = random.choice(tuple(t1))
                j = random.choice(tuple(t2))
                t1.remove(i); t2.remove(j); t1.add(j); t2.add(i)
            return (t1, t2, ex)

        def decode(indv):
            t1_idx, t2_idx, ex_idx = indv
            t1 = [players[i] for i in t1_idx]
            t2 = [players[i] for i in t2_idx]
            ex = [players[i] for i in ex_idx]
            return t1, t2, ex

        population = [make_individual() for _ in range(population_size)]
        best_score = -1.0
        best_split = None
        for _ in range(generations):
            scored = []
            for indv in population:
                t1, t2, ex = decode(indv)
                score, _ = self._evaluate_split(t1, t2)
                scored.append((score, indv))
                if score > best_score:
                    best_score = score
                    best_split = (list(t1), list(t2), list(ex))
            scored.sort(key=lambda x: x[0], reverse=True)
            elites = [indv for _, indv in scored[:max(2, population_size // 5)]]
            next_pop = elites.copy()
            while len(next_pop) < population_size:
                parents = random.sample(scored[:population_size // 2], 2)
                c1, c2 = crossover(parents[0][1], parents[1][1])
                next_pop.append(mutate(c1))
                if len(next_pop) < population_size:
                    next_pop.append(mutate(c2))
            population = next_pop

        if best_split is None:
            return self._balance_simple(players, team_size)
        team1, team2, extras = best_split
        score, analysis = self._evaluate_split(team1, team2)
        # Build simple alternatives by slight mutations of best
        alternatives = []
        for _ in range(3):
            if team1 and team2:
                i = random.randrange(len(team1))
                j = random.randrange(len(team2))
                t1 = team1.copy()
                t2 = team2.copy()
                t1[i], t2[j] = t2[j], t1[i]
                s, _ = self._evaluate_split(t1, t2)
                alternatives.append((t1, t2))
        return TeamBalanceResult(team1=team1, team2=team2, extras=extras, balance_score=score, confidence=self._confidence(score), analysis=analysis, alternative_arrangements=alternatives)

    def _evaluate_split(self, team1: List[SelectedPlayer], team2: List[SelectedPlayer]) -> Tuple[float, Dict[str, Any]]:
        t1_r = np.array([p.skill_rating or 1000.0 for p in team1], dtype=float)
        t2_r = np.array([p.skill_rating or 1000.0 for p in team2], dtype=float)
        t1_avg = float(np.mean(t1_r)) if t1_r.size else 0.0
        t2_avg = float(np.mean(t2_r)) if t2_r.size else 0.0
        skill_diff = abs(t1_avg - t2_avg)
        skill_balance = max(0.0, 1.0 - (skill_diff / 500.0))

        t1_chars = [p.selected_character or "" for p in team1]
        t2_chars = [p.selected_character or "" for p in team2]
        synergy1 = self._team_synergy(t1_chars)
        synergy2 = self._team_synergy(t2_chars)
        synergy_balance = max(0.0, 1.0 - abs(synergy1 - synergy2))

        role_balance = 0.5
        tier_balance = 0.5
        comfort_balance = 0.5
        meta_balance = 0.5

        weights = self._weights
        score = (
            skill_balance * weights["skill_balance"]
            + synergy_balance * weights["synergy_balance"]
            + role_balance * weights["role_balance"]
            + tier_balance * weights["tier_balance"]
            + comfort_balance * weights["comfort_balance"]
            + meta_balance * weights["meta_balance"]
        )
        analysis = {
            "t1_avg_skill": t1_avg,
            "t2_avg_skill": t2_avg,
            "skill_diff": skill_diff,
            "synergy_team1": synergy1,
            "synergy_team2": synergy2,
            "skill_balance": skill_balance,
            "synergy_balance": synergy_balance,
        }
        return score, analysis

    def _team_synergy(self, chars: List[str]) -> float:
        total = 0.0
        count = 0
        for i in range(len(chars)):
            for j in range(i + 1, len(chars)):
                total += self._synergy.get(self._pair(chars[i], chars[j]), 0.0)
                count += 1
        return total / count if count else 0.0

    def _pair(self, a: str, b: str) -> Tuple[str, str]:
        if a <= b:
            return (a, b)
        return (b, a)

    def _load_synergy(self) -> Dict[Tuple[str, str], float]:
        path = os.path.join("data", "character_synergies.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            mat: Dict[Tuple[str, str], float] = {}
            for k, v in raw.items():
                parts = k.split("|")
                if len(parts) == 2:
                    mat[self._pair(parts[0], parts[1])] = float(v)
            return mat
        except Exception:
            return {}

    def _confidence(self, score: float) -> float:
        if score >= 0.9:
            return 0.9
        if score >= 0.8:
            return 0.8
        if score >= 0.7:
            return 0.7
        return 0.6

    def _extract_team_features(self, team: List[SelectedPlayer]) -> PostSelectionFeatures:
        features = PostSelectionFeatures()
        ratings = np.array([p.skill_rating or 1000.0 for p in team], dtype=float)
        if ratings.size:
            features.avg_skill_rating = float(np.mean(ratings))
            features.skill_variance = float(np.var(ratings))
        comforts = np.array([p.character_proficiency or 0.5 for p in team], dtype=float)
        features.character_comfort_avg = float(np.mean(comforts)) if comforts.size else 0.0
        features.team_synergy_score = 0.0
        features.role_coverage = []
        features.tier_distribution = {}
        features.detection_vs_stealth_balance = 0.0
        features.meta_strength_score = 0.0
        return features

    def _calculate_skill_balance(self, t1: PostSelectionFeatures, t2: PostSelectionFeatures) -> float:
        diff = abs(t1.avg_skill_rating - t2.avg_skill_rating)
        return max(0.0, 1.0 - (diff / 500.0))

    def _calculate_synergy_balance(self, t1: PostSelectionFeatures, t2: PostSelectionFeatures) -> float:
        return max(0.0, 1.0 - abs(t1.team_synergy_score - t2.team_synergy_score))


# -------- Discord UI Views --------

class TeamCompositionChoiceView(discord.ui.View):
    def __init__(self, draft: 'DraftSession', bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)
        self.draft = draft
        self.bot_commands = bot_commands
        # Always allow manual selection
        self.add_item(ManualTeamSelectionButton())
        # Hide AI-related buttons for real-world drafts; only show in simulation mode
        if draft.is_simulation:
            self.add_item(AutoBalanceButton('genetic'))
            self.add_item(AutoBalanceButton('monte_carlo'))
            self.add_item(AutoBalanceButton('simple'))
            self.add_item(ShowAIAnalysisButton())


class ManualTeamSelectionButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🎯 수동 팀 선택", style=discord.ButtonStyle.primary, custom_id="manual_team_selection")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: TeamCompositionChoiceView = self.view  # type: ignore
        user_id = interaction.user.id
        if (view.draft.is_test_mode and user_id == view.draft.real_user_id) or user_id in view.draft.captains:
            await interaction.response.send_message("🎯 수동 팀 선택으로 진행할게.", ephemeral=True)
            await view.bot_commands._start_team_selection(view.draft, view.draft.channel_id)
        else:
            await interaction.response.send_message("팀장만 팀 구성 방법을 선택할 수 있어.", ephemeral=True)


class AutoBalanceButton(discord.ui.Button):
    def __init__(self, algorithm: str):
        super().__init__(label=f"🤖 AI 자동 구성 ({algorithm})", style=discord.ButtonStyle.success, custom_id=f"auto_balance_{algorithm}")
        self.algorithm = algorithm

    async def callback(self, interaction: discord.Interaction) -> None:
        view: TeamCompositionChoiceView = self.view  # type: ignore
        # Safety: do not allow in real-world drafts (should be hidden already)
        if not getattr(view.draft, 'is_simulation', False):
            await interaction.response.send_message("AI 자동 구성은 현재 숨겨져 있어.", ephemeral=True)
            return
        user_id = interaction.user.id
        if (view.draft.is_test_mode and user_id == view.draft.real_user_id) or user_id in view.draft.captains:
            await interaction.response.send_message(f"🤖 AI 자동 구성 ({self.algorithm})을 선택했어!", ephemeral=True)
            await view.bot_commands._perform_automatic_team_balancing(view.draft, self.algorithm)
        else:
            await interaction.response.send_message("팀장만 팀 구성 방법을 선택할 수 있어.", ephemeral=True)


class ShowAIAnalysisButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📊 AI 분석 먼저 보기", style=discord.ButtonStyle.secondary, custom_id="show_ai_analysis")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: TeamCompositionChoiceView = self.view  # type: ignore
        # Safety: do not allow in real-world drafts (should be hidden already)
        if not getattr(view.draft, 'is_simulation', False):
            await interaction.response.send_message("AI 분석 기능은 현재 숨겨져 있어.", ephemeral=True)
            return
        try:
            # Build SelectedPlayer list from current draft without applying
            draft = view.draft
            bot = view.bot_commands
            try:
                roster = bot.roster_store.load(draft.guild_id)
                rating_map = {p.user_id: p.rating for p in roster}
                prof_map = {p.user_id: getattr(p, 'servant_ratings', {}) for p in roster}
            except Exception:
                rating_map, prof_map = {}, {}

            selected_players: List[SelectedPlayer] = []
            for uid, player in draft.players.items():
                char = draft.confirmed_servants.get(uid) or player.selected_servant
                if not char:
                    continue
                selected_players.append(
                    SelectedPlayer(
                        user_id=uid,
                        display_name=player.username,
                        selected_character=char,
                        skill_rating=rating_map.get(uid),
                        character_proficiency=(prof_map.get(uid, {}) or {}).get(char)
                    )
                )

            # Quick analysis using 'monte_carlo' label (same logic for now)
            req = TeamBalanceRequest(players=selected_players, team_size=draft.team_size, balance_algorithm='monte_carlo')
            result = bot.post_selection_balancer.balance_teams(req)

            # Prepare embed preview
            embed = discord.Embed(
                title="📊 AI 분석 결과 (미리보기)",
                description="현재 캐릭터 선택을 바탕으로 한 AI 분석이야",
                color=discord.Color.blurple()
            )
            team1_preview = "\n".join([f"• **{p.selected_character}** - {p.display_name}" for p in result.team1])
            team2_preview = "\n".join([f"• **{p.selected_character}** - {p.display_name}" for p in result.team2])
            embed.add_field(name="예상 팀 1", value=team1_preview or "-", inline=True)
            embed.add_field(name="예상 팀 2", value=team2_preview or "-", inline=True)
            embed.add_field(
                name="🎯 밸런스 평가",
                value=(
                    f"예상 밸런스: {result.balance_score:.1%}\n"
                    f"신뢰도: {result.confidence:.1%}\n"
                    f"권장도: {'높음' if result.balance_score > 0.8 else '보통' if result.balance_score > 0.6 else '낮음'}"
                ),
                inline=False
            )
            embed.add_field(name="ℹ️ 참고", value="이것은 분석 결과일 뿐이야. 여전히 수동 또는 자동을 선택할 수 있어.", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ AI 분석 중 문제가 발생했어. 다른 방법을 선택해줘.", ephemeral=True)


class BalanceResultView(discord.ui.View):
    def __init__(self, draft: 'DraftSession', result: TeamBalanceResult, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)
        self.draft = draft
        self.result = result
        self.bot_commands = bot_commands
        self.add_item(AcceptBalanceButton())
        self.add_item(ShowAlternativesButton())
        self.add_item(TryDifferentAlgorithmButton())
        self.add_item(SwitchToManualButton())


class AcceptBalanceButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ 이 구성으로 확정", style=discord.ButtonStyle.success, custom_id="accept_balance")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: BalanceResultView = self.view  # type: ignore
        user_id = interaction.user.id
        if (view.draft.is_test_mode and user_id == view.draft.real_user_id) or user_id in view.draft.captains:
            await interaction.response.send_message("✅ AI 자동 구성을 확정했어! 드래프트가 완료됐어.", ephemeral=True)
            await view.bot_commands._complete_draft(view.draft)
        else:
            await interaction.response.send_message("팀장만 최종 확정을 할 수 있어.", ephemeral=True)


class ShowAlternativesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔄 다른 구성 보기", style=discord.ButtonStyle.secondary, custom_id="show_alternatives")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: BalanceResultView = self.view  # type: ignore
        if not view.result.alternative_arrangements:
            await interaction.response.send_message("현재 다른 좋은 구성 옵션이 없어.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🔄 대안 팀 구성",
            description="AI가 고려한 다른 좋은 팀 구성들이야",
            color=discord.Color.blurple()
        )
        for i, (alt_team1, alt_team2) in enumerate(view.result.alternative_arrangements[:3], 1):
            team1_text = ", ".join([p.display_name for p in alt_team1])
            team2_text = ", ".join([p.display_name for p in alt_team2])
            embed.add_field(name=f"대안 {i}", value=f"**팀1**: {team1_text}\n**팀2**: {team2_text}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TryDifferentAlgorithmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="⚙️ 다른 알고리즘 시도", style=discord.ButtonStyle.secondary, custom_id="try_different_algorithm")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: BalanceResultView = self.view  # type: ignore
        user_id = interaction.user.id
        if (view.draft.is_test_mode and user_id == view.draft.real_user_id) or user_id in view.draft.captains:
            current_algorithm = getattr(view.result, 'algorithm', 'simple')
            algorithms = ['genetic', 'monte_carlo', 'simple']
            next_algorithm = algorithms[(algorithms.index(current_algorithm) + 1) % len(algorithms)] if current_algorithm in algorithms else 'simple'
            await interaction.response.send_message(f"⚙️ {next_algorithm.upper()} 알고리즘을 시도해볼게!", ephemeral=True)
            await view.bot_commands._perform_automatic_team_balancing(view.draft, next_algorithm)
        else:
            await interaction.response.send_message("팀장만 알고리즘을 변경할 수 있어.", ephemeral=True)


class SwitchToManualButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🎯 수동 선택으로 변경", style=discord.ButtonStyle.primary, custom_id="switch_to_manual")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: BalanceResultView = self.view  # type: ignore
        user_id = interaction.user.id
        if (view.draft.is_test_mode and user_id == view.draft.real_user_id) or user_id in view.draft.captains:
            await interaction.response.send_message("🎯 수동 팀 선택으로 변경할게! 팀장들이 직접 선택해줘.", ephemeral=True)
            for player in view.draft.players.values():
                player.team = None
            if view.draft.captains:
                view.draft.players[view.draft.captains[0]].team = 1
            if len(view.draft.captains) > 1:
                view.draft.players[view.draft.captains[1]].team = 2
            await view.bot_commands._start_team_selection(view.draft, view.draft.channel_id)
        else:
            await interaction.response.send_message("팀장만 선택 방법을 변경할 수 있어.", ephemeral=True)



