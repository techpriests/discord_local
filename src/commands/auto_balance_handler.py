"""
AutoBalance Handler for team draft functionality.
Extracted from team_draft.py to improve code organization.
"""

import discord
import logging
from typing import List, TYPE_CHECKING
from discord.ext import commands

if TYPE_CHECKING:
    from src.commands.team_draft import DraftSession, TeamDraftCommands

from src.commands.auto_balance import (
    SelectedPlayer,
    TeamBalanceRequest,
    TeamBalanceResult,
    BalanceResultView
)

logger = logging.getLogger(__name__)


class AutoBalanceHandler:
    """Handler for autobalance functionality extracted from TeamDraftCommands."""

    def __init__(self, bot_commands: 'TeamDraftCommands'):
        self.bot_commands = bot_commands
        self.post_selection_balancer = bot_commands.post_selection_balancer
        self.roster_store = bot_commands.roster_store
        self.auto_balance_config = bot_commands.auto_balance_config
        self.performance_monitor = getattr(bot_commands, 'performance_monitor', None)
        self.ml_trainer = getattr(bot_commands, 'ml_trainer', None)

    async def perform_automatic_team_balancing(self, draft: 'DraftSession', algorithm: str = 'simple') -> None:
        """Perform automatic balancing and present results; fall back to manual on error."""
        from src.commands.team_draft import INFO_COLOR, ERROR_COLOR, SUCCESS_COLOR, DraftPhase  # Avoid circular imports
        
        channel = self.bot_commands._get_draft_channel(draft)
        if not channel:
            return
        processing = discord.Embed(
            title="🤖 AI 팀 밸런싱 진행 중...",
            description=f"{algorithm.upper()} 알고리즘으로 계산 중",
            color=INFO_COLOR
        )
        msg = await channel.send(embed=processing)
        try:
            # Build SelectedPlayer list with roster ratings
            selected_players: List[SelectedPlayer] = []
            try:
                roster = self.roster_store.load(draft.guild_id)
                rating_map = {p.user_id: p.rating for p in roster}
                prof_map = {p.user_id: getattr(p, 'servant_ratings', {}) for p in roster}
            except Exception:
                rating_map, prof_map = {}, {}

            for uid, player in draft.players.items():
                char = draft.confirmed_servants.get(uid) or player.selected_servant
                selected_players.append(
                    SelectedPlayer(
                        user_id=uid,
                        display_name=player.username,
                        selected_character=char,
                        skill_rating=rating_map.get(uid),
                        character_proficiency=(prof_map.get(uid, {}) or {}).get(char)
                    )
                )

            req = TeamBalanceRequest(players=selected_players, team_size=draft.team_size, balance_algorithm=algorithm)
            result = self.post_selection_balancer.balance_teams(req)

            # Apply assignments
            for p in result.team1:
                if p.user_id in draft.players:
                    draft.players[p.user_id].team = 1
            for p in result.team2:
                if p.user_id in draft.players:
                    draft.players[p.user_id].team = 2
            for p in result.extras:
                if p.user_id in draft.players:
                    draft.players[p.user_id].team = None

            # Store result for accept/alternative actions
            draft.auto_balance_result = {
                "algorithm": algorithm,
                "balance_score": result.balance_score,
                "confidence": result.confidence,
                "team1": [(p.user_id, p.display_name, p.selected_character) for p in result.team1],
                "team2": [(p.user_id, p.display_name, p.selected_character) for p in result.team2],
                "extras": [(p.user_id, p.display_name, p.selected_character) for p in result.extras],
            }

            # Present results with actions
            embed = self.create_balance_result_embed(draft, result, algorithm)
            view = BalanceResultView(draft, result, self.bot_commands)
            # Log performance
            try:
                if self.performance_monitor:
                    self.performance_monitor.log_balance_attempt(algorithm, result.balance_score, float(result.analysis.get('processing_time', 0.0)), True)
            except Exception:
                pass
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Automatic balancing failed: {e}")
            await msg.edit(embed=discord.Embed(title="❌ 자동 밸런싱 실패", description="수동 선택으로 진행할게.", color=ERROR_COLOR))
            await self.bot_commands._start_team_selection(draft, draft.channel_id)

    def create_balance_result_embed(self, draft: 'DraftSession', result: TeamBalanceResult, algorithm: str) -> discord.Embed:
        from src.commands.team_draft import SUCCESS_COLOR  # Avoid circular imports
        
        embed = discord.Embed(
            title=f"🤖 AI 팀 밸런싱 완료 ({algorithm.upper()})",
            description=f"밸런스 점수: {result.balance_score:.1%} (신뢰도: {result.confidence:.1%})",
            color=SUCCESS_COLOR
        )
        t1 = "\n".join([f"**{p.selected_character or '?'}** - {p.display_name}" for p in result.team1])
        t2 = "\n".join([f"**{p.selected_character or '?'}** - {p.display_name}" for p in result.team2])
        embed.add_field(name=f"팀 1 ({len(result.team1)}명)", value=t1 or "-", inline=True)
        embed.add_field(name=f"팀 2 ({len(result.team2)}명)", value=t2 or "-", inline=True)
        return embed

    async def analyze_completed_draft_balance(self, ctx: commands.Context) -> None:
        """Analyze the balance of a completed draft."""
        from src.commands.team_draft import INFO_COLOR, DraftPhase  # Avoid circular imports
        
        channel_id = ctx.channel.id
        if channel_id not in self.bot_commands.active_drafts:
            await self.bot_commands.send_error(ctx, "진행 중인 드래프트가 없어")
            return
        draft = self.bot_commands.active_drafts[channel_id]
        if draft.phase != DraftPhase.COMPLETED:
            await self.bot_commands.send_error(ctx, "드래프트가 완료된 후에 분석할 수 있어")
            return
        if not draft.confirmed_servants:
            await self.bot_commands.send_error(ctx, "캐릭터 선택 정보가 없어")
            return

        try:
            team1_players = [p for p in draft.players.values() if p.team == 1]
            team2_players = [p for p in draft.players.values() if p.team == 2]

            team1_selected: List[SelectedPlayer] = []
            team2_selected: List[SelectedPlayer] = []

            for player in team1_players:
                character = draft.confirmed_servants.get(player.user_id)
                if character:
                    team1_selected.append(SelectedPlayer(user_id=player.user_id, display_name=player.username, selected_character=character))

            for player in team2_players:
                character = draft.confirmed_servants.get(player.user_id)
                if character:
                    team2_selected.append(SelectedPlayer(user_id=player.user_id, display_name=player.username, selected_character=character))

            balancer = self.post_selection_balancer
            team1_features = balancer._extract_team_features(team1_selected)
            team2_features = balancer._extract_team_features(team2_selected)

            skill_balance = balancer._calculate_skill_balance(team1_features, team2_features)
            synergy_balance = balancer._calculate_synergy_balance(team1_features, team2_features)

            embed = discord.Embed(
                title="📊 AI 드래프트 밸런스 분석",
                description="완료된 드래프트의 팀 밸런스를 AI가 분석했어",
                color=INFO_COLOR
            )
            overall_balance = (skill_balance + synergy_balance) / 2
            balance_emoji = "🟢" if overall_balance > 0.8 else "🟡" if overall_balance > 0.6 else "🔴"
            embed.add_field(name="🎯 종합 밸런스 평가", value=f"{balance_emoji} {overall_balance:.1%}", inline=False)
            embed.add_field(
                name="📈 세부 분석",
                value=(
                    f"스킬 밸런스: {skill_balance:.1%}\n"
                    f"시너지 밸런스: {synergy_balance:.1%}\n"
                    f"팀1 평균 스킬: {team1_features.avg_skill_rating:.0f}\n"
                    f"팀2 평균 스킬: {team2_features.avg_skill_rating:.0f}"
                ),
                inline=True
            )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Balance analysis failed: {e}")
            await self.bot_commands.send_error(ctx, "밸런스 분석 중 문제가 발생했어")

    async def generate_synergy_from_matches(self, ctx: commands.Context) -> None:
        """Generate synergy data from recorded matches."""
        try:
            if not self.ml_trainer:
                await self.bot_commands.send_error(ctx, "ML trainer가 초기화되지 않았어")
                return
            
            res = self.ml_trainer.learn_character_synergies_from_matches()
            if res.get('success'):
                await self.bot_commands.send_success(ctx, f"시너지 학습 완료: {res.get('pairs', 0)} 쌍, {res.get('matches', 0)} 경기")
            else:
                await self.bot_commands.send_error(ctx, f"시너지 학습 실패: {res}")
        except Exception as e:
            await self.bot_commands.send_error(ctx, f"시너지 학습 오류: {e}")

    async def train_balance_predictor(self, ctx: commands.Context) -> None:
        """Train balance predictor from existing data."""
        try:
            if not self.ml_trainer:
                await self.bot_commands.send_error(ctx, "ML trainer가 초기화되지 않았어")
                return
            
            res = self.ml_trainer.train_balance_predictor_from_existing_data()
            if res.get('success'):
                await self.bot_commands.send_success(ctx, f"학습 완료 (CV: {res.get('cv_mean', 0):.3f}±{res.get('cv_std', 0):.3f}, Val: {res.get('val_accuracy', 0):.3f})")
            else:
                await self.bot_commands.send_error(ctx, f"학습 실패: {res.get('error')}")
        except Exception as e:
            await self.bot_commands.send_error(ctx, f"학습 오류: {e}")

    async def update_balance_weights(self, ctx: commands.Context, *, weights: str) -> None:
        """Update AI balancing weights."""
        try:
            # weights example: skill=0.3,synergy=0.25,role=0.2,tier=0.1,comfort=0.1,meta=0.05
            parts = [p.strip() for p in weights.split(',') if p.strip()]
            mapping = {
                'skill': 'skill_balance',
                'synergy': 'synergy_balance',
                'role': 'role_balance',
                'tier': 'tier_balance',
                'comfort': 'comfort_balance',
                'meta': 'meta_balance',
            }
            new_weights = {}
            for part in parts:
                k, v = part.split('=')
                key = mapping.get(k.strip())
                if not key:
                    continue
                new_weights[key] = float(v)
            self.auto_balance_config.update_balance_weights(new_weights)
            await self.bot_commands.send_success(ctx, "가중치를 업데이트했어")
        except Exception as e:
            await self.bot_commands.send_error(ctx, f"설정 업데이트 실패: {e}")

    async def set_balance_algorithm(self, ctx: commands.Context, algorithm: str) -> None:
        """Set the default balance algorithm."""
        try:
            self.auto_balance_config.set_default_algorithm(algorithm)
            await self.bot_commands.send_success(ctx, f"기본 알고리즘을 {algorithm}로 설정했어")
        except Exception as e:
            await self.bot_commands.send_error(ctx, f"알고리즘 설정 실패: {e}")

    async def announce_final_auto_balanced_teams(self, draft: 'DraftSession', result: TeamBalanceResult) -> None:
        """Announce the final auto-balanced teams."""
        from src.commands.team_draft import SUCCESS_COLOR  # Avoid circular imports
        
        main_channel = self.bot_commands.bot.get_channel(draft.channel_id) if self.bot_commands.bot else None
        if not main_channel:
            return
        try:
            team_format = f"{draft.team_size}v{draft.team_size}"
            embed = discord.Embed(
                title=f"🤖 AI 자동 밸런싱 완료! ({team_format})",
                description=f"**인공지능이 최적의 밸런스로 팀을 구성했어!**\n밸런스 점수: {result.balance_score:.1%}",
                color=SUCCESS_COLOR
            )
            t1 = "\n".join([f"• **{p.selected_character or '?'}** - {p.display_name}" for p in result.team1])
            t2 = "\n".join([f"• **{p.selected_character or '?'}** - {p.display_name}" for p in result.team2])
            embed.add_field(name=f"팀 1 ({len(result.team1)}명)", value=t1 or "-", inline=True)
            embed.add_field(name=f"팀 2 ({len(result.team2)}명)", value=t2 or "-", inline=True)
            
            await self.bot_commands._safe_api_call(lambda: main_channel.send(embed=embed), bucket=f"auto_balance_announce_{draft.channel_id}")
        except Exception as e:
            logger.warning(f"Failed to announce auto-balanced teams: {e}")

