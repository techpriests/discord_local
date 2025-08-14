import logging
import random
import asyncio
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple, Union, Any
from enum import Enum
from dataclasses import dataclass, field
import discord
from discord.ext import commands
from discord import app_commands
import numpy as np

from src.utils.decorators import command_handler
from .base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR
from src.services.match_recorder import MatchRecorder, PlayerFeature
from src.services.roster_store import RosterStore, RosterPlayer
from src.services.auto_balance_config import AutoBalanceConfig
from src.services.performance_monitor import PerformanceMonitor, AlertSystem
from src.services.post_selection_ml import PostSelectionMLTrainer
from src.services.ab_test_validator import PostSelectionABTester, PostSelectionValidator

logger = logging.getLogger(__name__)

# Hot reload test comment - this should trigger the deployment action


from src.commands.auto_balance import (
    SelectedPlayer,
    TeamBalanceRequest,
    TeamBalanceResult,
    PostSelectionFeatures,
    PostSelectionTeamBalancer,
    TeamCompositionChoiceView,
)

def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        client = interaction.client
        if isinstance(client, commands.Bot):
            try:
                return await client.is_owner(interaction.user)
            except Exception:
                return False
        return False
    return app_commands.check(predicate)

class DraftPhase(Enum):
    """Phases of the draft system"""
    WAITING = "waiting"
    CAPTAIN_VOTING = "captain_voting"
    SERVANT_BAN = "servant_ban"
    SERVANT_SELECTION = "servant_selection"
    SERVANT_RESELECTION = "servant_reselection"
    TEAM_SELECTION = "team_selection"
    COMPLETED = "completed"


@dataclass
class Player:
    """Represents a player in the draft"""
    user_id: int
    username: str
    selected_servant: Optional[str] = None
    team: Optional[int] = None  # 1 or 2
    is_captain: bool = False


@dataclass
class DraftSession:
    """Represents an active draft session"""
    channel_id: int
    guild_id: int
    team_size: int = 6  # Number of players per team (2 for 2v2, 3 for 3v3, 5 for 5v5, 6 for 6v6)
    phase: DraftPhase = DraftPhase.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    # Who started this draft (used for permissions on finish/result)
    started_by_user_id: Optional[int] = None
    
    # Thread support for clean draft environment
    thread_id: Optional[int] = None  # Thread where draft takes place
    
    # Test mode tracking
    is_test_mode: bool = False
    real_user_id: Optional[int] = None  # The real user in test mode
    # Simulation mode (balanced by expert) for logging
    is_simulation: bool = False
    simulation_session_id: Optional[str] = None
    simulation_author_id: Optional[int] = None
    
    # Captain selection
    captain_vote_message_id: Optional[int] = None
    captains: List[int] = field(default_factory=list)  # user_ids
    
    # Captain voting progress tracking (similar to servant selection)
    captain_voting_progress: Dict[int, int] = field(default_factory=dict)  # user_id -> number of votes cast
    captain_voting_progress_message_id: Optional[int] = None
    captain_voting_start_time: Optional[float] = None  # timestamp when voting started
    captain_voting_time_limit: int = 120  # 2 minutes in seconds
    
    # Servant tier definitions for ban system
    servant_tiers: Dict[str, List[str]] = field(default_factory=lambda: {
        "S": ["헤클", "길가", "란슬", "가재"],  # '란슬' moved to S, '네로' moved to A
        "A": ["세이버", "네로", "카르나", "룰러"],  # '네로' moved to A, '란슬' moved to S
        "B": ["디미", "이칸", "산노", "서문", "바토리"]
    })
    
    # Servant selection - organized by categories
    servant_categories: Dict[str, List[str]] = field(default_factory=lambda: {
        "세이버": ["세이버", "흑화 세이버", "가웨인", "네로", "모드레드", "무사시", "지크"],
        "랜서": ["쿠훌린", "디미", "가재", "카르나", "바토리"],
        "아처": ["아처", "길가", "아엑", "아탈"],
        "라이더": ["메두사", "이칸", "라엑", "톨포"],
        "캐스터": ["메데이아", "질드레", "타마", "너서리", "셰익", "안데"],
        "어새신": ["허새", "징어", "서문", "잭더리퍼", "세미", "산노", "시키"],
        "버서커": ["헤클", "란슬", "여포", "프랑"],
        "엑스트라": ["어벤저", "룰러", "멜트", "암굴"]
    })
    available_servants: Set[str] = field(default_factory=lambda: {
        # Flatten all categories into a single set
        "세이버", "흑화 세이버", "가웨인", "네로", "모드레드", "무사시", "지크",
        "쿠훌린", "디미", "가재", "카르나", "바토리",
        "아처", "길가", "아엑", "아탈",
        "메두사", "이칸", "라엑", "톨포",
        "메데이아", "질드레", "타마", "너서리", "셰익", "안데",
        "허새", "징어", "서문", "잭더리퍼", "세미", "산노", "시키",
        "헤클", "란슬", "여포", "프랑",
        "어벤저", "룰러", "멜트", "암굴"
    })
    
    # Special ability servants
    detection_servants: Set[str] = field(default_factory=lambda: {
        "아처", "룰러", "너서리", "아탈", "가웨인", "디미", "허새"
    })
    cloaking_servants: Set[str] = field(default_factory=lambda: {
        "서문", "징어", "잭더리퍼", "세미", "안데"
    })
    conflicted_servants: Dict[str, List[int]] = field(default_factory=dict)
    confirmed_servants: Dict[int, str] = field(default_factory=dict)
    
    # Team selection with confirmation support
    first_pick_captain: Optional[int] = None
    team_selection_round: int = 1
    current_picking_captain: Optional[int] = None
    picks_this_round: Dict[int, int] = field(default_factory=dict)  # captain_id -> picks_made
    pending_team_selections: Dict[int, List[int]] = field(default_factory=dict)  # captain_id -> [pending_user_ids]
    team_selection_progress: Dict[int, Dict[int, bool]] = field(default_factory=dict)  # captain_id -> {round -> completed}
    
    # Servant ban phase - enhanced for new system
    banned_servants: Set[str] = field(default_factory=set)
    system_bans: List[str] = field(default_factory=list)  # System's automated bans
    captain_bans: Dict[int, List[str]] = field(default_factory=dict)  # captain_id -> banned_servants
    captain_ban_progress: Dict[int, bool] = field(default_factory=dict)  # captain_id -> completed
    captain_ban_order: List[int] = field(default_factory=list)  # Order of captain bans determined by dice
    current_banning_captain: Optional[int] = None  # Which captain is currently banning
    
    # Servant selection progress tracking
    selection_progress: Dict[int, bool] = field(default_factory=dict)  # user_id -> completed
    reselection_round: int = 0  # Track reselection rounds to prevent infinite loops
    
    # Servant selection time limits
    selection_start_time: Optional[float] = None  # timestamp when selection started
    selection_time_limit: int = 90  # 1 minute 30 seconds
    reselection_start_time: Optional[float] = None  # timestamp when reselection started
    reselection_time_limit: int = 90  # 1 minute 30 seconds
    
    # Task tracking for proper cleanup
    running_tasks: Set = field(default_factory=set)  # Track background tasks
    

    
    # Messages for state tracking
    status_message_id: Optional[int] = None
    ban_progress_message_id: Optional[int] = None
    selection_progress_message_id: Optional[int] = None
    selection_buttons_message_id: Optional[int] = None  # Separate message for buttons
    last_progress_update_hash: Optional[str] = field(default=None)  # Prevent unnecessary view recreation
    last_voting_progress_hash: Optional[str] = field(default=None)  # Prevent unnecessary captain voting updates

    # Join-based start support
    join_target_total_players: Optional[int] = None
    join_user_ids: Set[int] = field(default_factory=set)
    join_message_id: Optional[int] = None
    # Match identifier for prematch/outcome correlation (optional)
    match_id: Optional[str] = None
    # Finish/outcome handling
    finish_view_message_id: Optional[int] = None
    outcome_recorded: bool = False
    # Auto-balance result storage for review/acceptance
    auto_balance_result: Optional[Dict[str, Any]] = None



class TeamDraftCommands(BaseCommands):
    """Commands for team draft system"""
    
    def __init__(self, bot: commands.Bot = None) -> None:
        """Initialize team draft commands

        Args:
            bot: Discord bot instance
        """
        super().__init__()
        self.bot = bot
        self.active_drafts: Dict[int, DraftSession] = {}  # channel_id -> DraftSession
        self.draft_start_times: Dict[int, float] = {}  # channel_id -> timestamp
        
        # View tracking for memory management
        self.active_views: Dict[int, List[discord.ui.View]] = {}  # channel_id -> views
        
        # Audit logging
        self.audit_logs: List[Dict] = []  # Simple in-memory audit log
        self.max_audit_logs = 1000  # Keep last 1000 events
        
        # Cleanup task will be scheduled when cog is fully loaded
        
        # Rate limiting for Discord API calls
        self.rate_limit_buckets: Dict[str, float] = {}  # bucket -> last_call_time
        self.api_call_counts: Dict[str, int] = {}  # bucket -> call_count
        
        # Selection patterns for team picking
        self.team_selection_patterns = {
            2: [  # 2v2 pattern
                {"first_pick": 1, "second_pick": 1},  # Round 1: Each captain picks 1
            ],
            3: [  # 3v3 pattern
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 1, "second_pick": 0},  # Round 2: First picks 1, Second picks 0
            ],
            5: [  # 5v5 pattern
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 2, "second_pick": 2},  # Round 2: Each picks 2
                {"first_pick": 1, "second_pick": 0},  # Round 3: First picks 1, Second picks 0
            ],
            6: [  # 6v6 pattern
                {"first_pick": 1, "second_pick": 2},  # Round 1
                {"first_pick": 2, "second_pick": 2},  # Round 2
                {"first_pick": 2, "second_pick": 1},  # Round 3
            ]
        }
        # Match recorder for ML data collection
        self.match_recorder = MatchRecorder()
        # Guild roster store for simulations
        self.roster_store = RosterStore()
        # New post-selection balancer (auto draft integration)
        self.auto_balance_config = AutoBalanceConfig()
        self.post_selection_balancer = PostSelectionTeamBalancer(self.roster_store)
        self.performance_monitor = PerformanceMonitor()
        self.alert_system = AlertSystem(self.performance_monitor)
        self.ml_trainer = PostSelectionMLTrainer(self.match_recorder, self.roster_store)

    async def cog_load(self) -> None:
        """Start background cleanup task after cog is loaded."""
        if self.bot:
            self.bot.loop.create_task(self._cleanup_task())

    async def _offer_team_composition_options(self, draft: DraftSession) -> None:
        """Offer manual vs AI auto-balance options after selection."""
        channel = self._get_draft_channel(draft)
        if not channel:
            return
        embed = discord.Embed(
            title="👥 팀 구성 방법 선택",
            description="서번트 선택이 끝났어! 이제 어떻게 팀을 구성할지 선택해줘:",
            color=INFO_COLOR
        )
        embed.add_field(
            name="🎯 수동 팀 선택 (기존 방식)",
            value="팀장이 직접 선택하는 전통적인 방식",
            inline=False
        )

        # Hide AI option text for real-world drafts; show only in simulation
        if getattr(draft, 'is_simulation', False):
            embed.add_field(
                name="🤖 AI 자동 밸런싱",
                value="인공지능이 최적 밸런스로 팀을 구성",
                inline=False
            )

        view = TeamCompositionChoiceView(draft, self)
        self._register_view(draft.channel_id, view)
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"composition_choice_{draft.channel_id}"
        )

    async def _perform_automatic_team_balancing(self, draft: DraftSession, algorithm: str = 'simple') -> None:
        """Perform automatic balancing and present results; fall back to manual on error."""
        channel = self._get_draft_channel(draft)
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
            embed = self._create_balance_result_embed(draft, result, algorithm)
            from src.commands.auto_balance import BalanceResultView  # local import to avoid cycles
            view = BalanceResultView(draft, result, self)
            # Log performance
            try:
                self.performance_monitor.log_balance_attempt(algorithm, result.balance_score, float(result.analysis.get('processing_time', 0.0)), True)
            except Exception:
                pass
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Automatic balancing failed: {e}")
            await msg.edit(embed=discord.Embed(title="❌ 자동 밸런싱 실패", description="수동 선택으로 진행할게.", color=ERROR_COLOR))
            await self._start_team_selection(draft, draft.channel_id)

    def _create_balance_result_embed(self, draft: DraftSession, result: TeamBalanceResult, algorithm: str) -> discord.Embed:
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

    @commands.command(
        name="밸런스분석",
        help="현재 완료된 드래프트의 밸런스를 AI가 분석해줘",
        brief="AI 밸런스 분석",
        hidden=True
    )
    async def analyze_completed_draft_balance(self, ctx: commands.Context) -> None:
        channel_id = ctx.channel.id
        if channel_id not in self.active_drafts:
            await self.send_error(ctx, "진행 중인 드래프트가 없어")
            return
        draft = self.active_drafts[channel_id]
        if draft.phase != DraftPhase.COMPLETED:
            await self.send_error(ctx, "드래프트가 완료된 후에 분석할 수 있어")
            return
        if not draft.confirmed_servants:
            await self.send_error(ctx, "캐릭터 선택 정보가 없어")
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
            await self.send_error(ctx, "밸런스 분석 중 문제가 발생했어")

    @commands.command(name="밸런스시너지", help="기록된 경기 데이터로부터 시너지 파일을 생성합니다 (owner-only)")
    @commands.is_owner()
    async def generate_synergy_from_matches(self, ctx: commands.Context) -> None:
        try:
            res = self.ml_trainer.learn_character_synergies_from_matches()
            if res.get('success'):
                await self.send_success(ctx, f"시너지 학습 완료: {res.get('pairs', 0)} 쌍, {res.get('matches', 0)} 경기")
            else:
                await self.send_error(ctx, f"시너지 학습 실패: {res}")
        except Exception as e:
            await self.send_error(ctx, f"시너지 학습 오류: {e}")

    @commands.command(name="밸런스학습", help="기존 데이터로 밸런스 예측 모델을 학습합니다 (owner-only)")
    @commands.is_owner()
    async def train_balance_predictor(self, ctx: commands.Context) -> None:
        try:
            res = self.ml_trainer.train_balance_predictor_from_existing_data()
            if res.get('success'):
                await self.send_success(ctx, f"학습 완료 (CV: {res.get('cv_mean', 0):.3f}±{res.get('cv_std', 0):.3f}, Val: {res.get('val_accuracy', 0):.3f})")
            else:
                await self.send_error(ctx, f"학습 실패: {res.get('error')}")
        except Exception as e:
            await self.send_error(ctx, f"학습 오류: {e}")

    @commands.command(name="밸런스설정", help="AI 밸런싱 가중치를 업데이트합니다 (owner-only)")
    @commands.is_owner()
    async def update_balance_weights(self, ctx: commands.Context, *, weights: str) -> None:
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
            await self.send_success(ctx, "가중치를 업데이트했어")
        except Exception as e:
            await self.send_error(ctx, f"설정 업데이트 실패: {e}")

    @commands.command(name="밸런스알고리즘", help="AI 밸런싱 알고리즘을 설정합니다 (owner-only)")
    @commands.is_owner()
    async def set_balance_algorithm(self, ctx: commands.Context, algorithm: str) -> None:
        try:
            self.auto_balance_config.set_default_algorithm(algorithm)
            await self.send_success(ctx, f"기본 알고리즘을 {algorithm}로 설정했어")
        except Exception as e:
            await self.send_error(ctx, f"알고리즘 설정 실패: {e}")

    async def _announce_final_auto_balanced_teams(self, draft: DraftSession, result: TeamBalanceResult) -> None:
        main_channel = self.bot.get_channel(draft.channel_id) if self.bot else None
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
            embed.add_field(name="팀 1 최종 로스터", value=t1 or "-", inline=True)
            embed.add_field(name="팀 2 최종 로스터", value=t2 or "-", inline=True)
            await self._safe_api_call(lambda: main_channel.send(embed=embed), bucket=f"auto_balance_announce_{draft.channel_id}")
        except Exception as e:
            logger.warning(f"Failed to announce auto-balanced teams: {e}")

    async def _cleanup_task(self) -> None:
        """Background task to clean up old drafts after 1 hour (2 hours if waiting for outcome)"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                current_time = time.time()
                expired_channels = []
                
                for channel_id, start_time in self.draft_start_times.items():
                    # Determine timeout based on phase: if roster completed and waiting for outcome, use 2 hours
                    draft = self.active_drafts.get(channel_id)
                    timeout_seconds = 7200 + 30 if (draft and draft.phase == DraftPhase.COMPLETED and not draft.outcome_recorded) else 3630
                    if current_time - start_time > timeout_seconds:
                        if draft:
                            # Skip very early stage only (captain voting), otherwise allow
                            if draft.phase != DraftPhase.CAPTAIN_VOTING:
                                expired_channels.append(channel_id)
                            else:
                                logger.info(f"Skipping cleanup of channel {channel_id} - still in captain voting phase")
                        else:
                            expired_channels.append(channel_id)
                
                for channel_id in expired_channels:
                    logger.info(f"Auto-cleaning expired draft in channel {channel_id} (safety check passed)")
                    
                    # Clean up draft state
                    if channel_id in self.active_drafts:
                        draft = self.active_drafts[channel_id]
                        
                        # Stop all active views to prevent memory leaks
                        await self._cleanup_views(channel_id)
                        
                        # Clean up all message IDs to prevent memory leaks
                        await self._cleanup_all_message_ids(draft)
                        
                        del self.active_drafts[channel_id]
                    if channel_id in self.draft_start_times:
                        del self.draft_start_times[channel_id]
                    
                    # Send cleanup notification to channel if possible
                    if self.bot:
                        try:
                            channel = self.bot.get_channel(channel_id)
                            if channel:
                                embed = discord.Embed(
                                    title="⏰ 드래프트 자동 정리",
                                    description="시간이 지나서 드래프트를 자동으로 정리했어.",
                                    color=INFO_COLOR
                                )
                                await self._safe_api_call(
                                    lambda: channel.send(embed=embed),
                                    bucket=f"cleanup_{channel_id}"
                                )
                        except Exception as e:
                            logger.warning(f"Failed to send cleanup notification: {e}")
                            
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    # -------------------------
    # Join-based draft start
    # -------------------------
    @commands.command(
        name="페어시작",
        help="버튼으로 참가를 받아 드래프트를 시작해. 사용법: 뮤 페어시작 <총인원수:짝수> (예: 12)",
        brief="드래프트 참가 모집",
        aliases=["draft_join_start"],
        description="뮤 페어시작 12 처럼 입력하면 참가 버튼이 있는 메시지를 보내. 인원이 차면 팀장 투표로 진행돼."
    )
    async def draft_start_join_chat(self, ctx: commands.Context, total_players: int = 12) -> None:
        if total_players % 2 != 0 or total_players <= 0:
            await self.send_error(ctx, "총 인원수는 2의 배수여야 해")
            return
        if total_players // 2 not in [2, 3, 5, 6]:
            await self.send_error(ctx, "팀 크기는 2,3,5,6 중 하나여야 해 (예: 12, 6v6)")
            return
        channel_id = ctx.channel.id
        guild_id = ctx.guild.id if ctx.guild else 0
        if channel_id in self.active_drafts:
            await self.send_error(ctx, "이미 진행 중인 드래프트가 있어.")
            return
        team_size = total_players // 2
        draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
        draft.started_by_user_id = ctx.author.id
        draft.join_target_total_players = total_players
        self.active_drafts[channel_id] = draft
        self.draft_start_times[channel_id] = time.time()

        embed = discord.Embed(
            title=f"🏁 드래프트 참가 모집 ({team_size}v{team_size})",
            description="아래 버튼을 눌러 참가하거나 취소해. 인원이 차면 자동으로 진행돼.",
            color=INFO_COLOR,
        )
        embed.add_field(name="필요 인원", value=f"{len(draft.join_user_ids)}/{total_players}")
        embed.add_field(name="참가자", value="없음", inline=False)

        view = JoinDraftView(draft, self)
        self._register_view(channel_id, view)
        msg = await ctx.send(embed=embed, view=view)
        draft.join_message_id = msg.id

    @app_commands.command(name="페어시작", description="버튼으로 참가를 받아 드래프트를 시작해. (예: 12명)")
    async def draft_start_join_slash(self, interaction: discord.Interaction, total_players: int = 12) -> None:
        if total_players % 2 != 0 or total_players <= 0:
            await self.send_error(interaction, "총 인원수는 2의 배수여야 해")
            return
        if total_players // 2 not in [2, 3, 5, 6]:
            await self.send_error(interaction, "팀 크기는 2,3,5,6 중 하나여야 해 (예: 12, 6v6)")
            return
        channel_id = interaction.channel_id or 0
        guild_id = interaction.guild_id or 0
        if channel_id in self.active_drafts:
            await self.send_error(interaction, "이미 진행 중인 드래프트가 있어.")
            return
        team_size = total_players // 2
        draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
        draft.started_by_user_id = interaction.user.id
        draft.join_target_total_players = total_players
        self.active_drafts[channel_id] = draft
        self.draft_start_times[channel_id] = time.time()

        embed = discord.Embed(
            title=f"🏁 드래프트 참가 모집 ({team_size}v{team_size})",
            description="아래 버튼을 눌러 참가하거나 취소해. 인원이 차면 자동으로 진행돼.",
            color=INFO_COLOR,
        )
        embed.add_field(name="필요 인원", value=f"0/{total_players}")
        embed.add_field(name="참가자", value="없음", inline=False)

        view = JoinDraftView(draft, self)
        self._register_view(channel_id, view)
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_response()
        else:
            msg = await interaction.followup.send(embed=embed, view=view, wait=True)
        draft.join_message_id = msg.id

    # Simulation commands that were previously outside the class
    @commands.command(
        name="페어시뮬",
        help="경험 많은 팀장이 양 팀을 모두 구성하는 시뮬레이션 드래프트를 시작합니다 (기본 6v6)",
        brief="시뮬 드래프트",
        description="사용법: 뮤 페어시뮬 [team_size:숫자] [players:@...]")
    async def draft_simulate_prefix(self, ctx: commands.Context, *, args: str = "") -> None:
        await self._handle_simulation_start(ctx, args)



    @command_handler()
    async def _handle_simulation_start(self, ctx_or_interaction: CommandContext, args: str = "") -> None:
        # Parse team_size (default 6)
        team_size = 6
        lowered = args.lower()
        if "team_size:2" in lowered or "team_size=2" in lowered:
            team_size = 2
        elif "team_size:3" in lowered or "team_size=3" in lowered:
            team_size = 3
        elif "team_size:5" in lowered or "team_size=5" in lowered:
            team_size = 5
        elif "team_size:6" in lowered or "team_size=6" in lowered:
            team_size = 6
        
        if team_size not in [2, 3, 5, 6]:
            await self.send_error(ctx_or_interaction, "팀 크기는 2, 3, 5, 6 중 하나여야 해")
            return
            
        total_players = team_size * 2
        channel_id = self.get_channel_id(ctx_or_interaction)
        guild_id = self.get_guild_id(ctx_or_interaction) or 0
        
        if channel_id in self.active_drafts:
            await self.send_error(ctx_or_interaction, "이미 진행 중인 드래프트가 있어.")
            return
            
        # Create draft
        draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
        draft.is_simulation = True
        draft.started_by_user_id = self.get_user_id(ctx_or_interaction)
        
        self.active_drafts[channel_id] = draft
        self.draft_start_times[channel_id] = time.time()
        
        await self.send_success(ctx_or_interaction, f"시뮬레이션 드래프트가 시작되었어! ({team_size}v{team_size})")

    # Status, cancel, and test commands that were previously outside the class

    @commands.command(
        name="페어상태",
        help="현재 드래프트 상태를 확인해",
        brief="드래프트 상태",
        aliases=["draft_status"]
    )
    async def draft_status_chat(self, ctx: commands.Context) -> None:
        """Check current draft status"""
        await self._handle_draft_status(ctx)

    @command_handler()
    async def _handle_draft_status(self, ctx_or_interaction: CommandContext) -> None:
        """Handle draft status check"""
        channel_id = self.get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_drafts:
            await self.send_response(ctx_or_interaction, "진행 중인 드래프트가 없어.")
            return
            
        draft = self.active_drafts[channel_id]
        embed = discord.Embed(
            title="📊 드래프트 상태",
            description=f"현재 단계: {draft.phase.value}",
            color=INFO_COLOR
        )
        
        embed.add_field(
            name="팀 구성",
            value=f"{draft.team_size}v{draft.team_size} ({len(draft.players)}/{draft.team_size * 2}명)",
            inline=True
        )
        
        if draft.captains:
            captain_names = [draft.players[cap_id].username for cap_id in draft.captains if cap_id in draft.players]
            embed.add_field(name="팀장", value=", ".join(captain_names), inline=True)
            
        await self.send_response(ctx_or_interaction, embed=embed)

    @commands.command(
        name="페어취소",
        help="진행 중인 드래프트를 취소해",
        brief="드래프트 취소",
        aliases=["draft_cancel"]
    )
    async def draft_cancel_chat(self, ctx: commands.Context) -> None:
        """Cancel current draft"""
        await self._handle_draft_cancel(ctx)

    async def _handle_draft_cancel(self, ctx_or_interaction: CommandContext) -> None:
        """Handle draft cancellation"""
        channel_id = self.get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_drafts:
            await self.send_error(ctx_or_interaction, "취소할 드래프트가 없어.")
            return
            
        draft = self.active_drafts[channel_id]
        
        # Clean up
        await self._cleanup_views(channel_id)
        await self._cleanup_all_message_ids(draft)
        
        # Remove from tracking
        del self.active_drafts[channel_id]
        if channel_id in self.draft_start_times:
            del self.draft_start_times[channel_id]
        
        await self.send_success(ctx_or_interaction, "드래프트를 취소했어.")

    # Utility methods that were previously outside the class
    async def _cleanup_views(self, channel_id: int) -> None:
        """Clean up all registered views for a channel"""
        if channel_id in self.registered_views:
            try:
                # Stop all views gracefully with timeout handling
                views_to_stop = list(self.registered_views[channel_id])
                for view in views_to_stop:
                    try:
                        if not view.is_finished():
                            view.stop()
                    except Exception as e:
                        logger.warning(f"Failed to stop view {type(view).__name__}: {e}")
                        
                # Clear the channel's views
                del self.registered_views[channel_id]
                logger.info(f"Cleaned up {len(views_to_stop)} views for channel {channel_id}")
            except Exception as e:
                logger.error(f"Error during view cleanup for channel {channel_id}: {e}")

    async def _cleanup_all_message_ids(self, draft: DraftSession) -> None:
        """Clean up all message IDs to prevent memory leaks"""
        try:
            # Clear various message IDs
            draft.captain_voting_message_id = None
            draft.selection_progress_message_id = None
            draft.join_message_id = None
            
            # Clear any message IDs stored in collections
            if hasattr(draft, 'ban_interface_message_ids'):
                draft.ban_interface_message_ids.clear()
            if hasattr(draft, 'selection_interface_message_ids'):
                draft.selection_interface_message_ids.clear()
            if hasattr(draft, 'team_selection_message_ids'):
                draft.team_selection_message_ids.clear()
                
            logger.debug(f"Cleaned up message IDs for draft in channel {draft.channel_id}")
        except Exception as e:
            logger.warning(f"Error cleaning up message IDs: {e}")

    def _sanitize_username(self, username: str) -> str:
        """Sanitize username to prevent Discord embed issues"""
        # Remove or escape characters that could break Discord embeds
        sanitized = username.replace('`', '\\`')  # Escape backticks
        sanitized = sanitized.replace('*', '\\*')  # Escape asterisks
        sanitized = sanitized.replace('_', '\\_')  # Escape underscores
        sanitized = sanitized.replace('~', '\\~')  # Escape tildes
        sanitized = sanitized.replace('|', '\\|')  # Escape pipes
        sanitized = sanitized.replace('[', '\\[')  # Escape brackets
        sanitized = sanitized.replace(']', '\\]')  # Escape brackets
        sanitized = sanitized.replace('(', '\\(')  # Escape parentheses
        sanitized = sanitized.replace(')', '\\)')  # Escape parentheses
        
        # Limit length to prevent extremely long names
        if len(sanitized) > 32:
            sanitized = sanitized[:29] + "..."
            
        return sanitized

    def _register_view(self, channel_id: int, view: discord.ui.View) -> None:
        """Register a view for cleanup tracking"""
        if channel_id not in self.registered_views:
            self.registered_views[channel_id] = []
        self.registered_views[channel_id].append(view)

    async def _safe_api_call(self, call_func, bucket: str = "default", max_retries: int = 3):
        """Safely make Discord API calls with rate limiting and retry logic"""
        
        for attempt in range(max_retries):
            try:
                # Check rate limit bucket
                current_time = time.time()
                last_call = self.rate_limit_buckets.get(bucket, 0)
                call_count = self.api_call_counts.get(bucket, 0)
                
                # Reset call count every minute
                if current_time - last_call > 60:
                    self.api_call_counts[bucket] = 0
                    call_count = 0
                
                # Rate limit: max 50 calls per minute per bucket
                if call_count >= 50:
                    wait_time = 60 - (current_time - last_call)
                    if wait_time > 0:
                        logger.info(f"Rate limiting bucket '{bucket}', waiting {wait_time:.1f}s")
                        await asyncio.sleep(wait_time)
                        self.api_call_counts[bucket] = 0
                
                # Update counters
                self.rate_limit_buckets[bucket] = current_time
                self.api_call_counts[bucket] = call_count + 1
                
                # Make the API call
                return await call_func()
                
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else (2 ** attempt)
                    logger.warning(f"Discord rate limit hit, retrying after {retry_after}s (attempt {attempt+1})")
                    await asyncio.sleep(retry_after)
                    continue
                elif e.status >= 500:  # Server error
                    wait_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff with jitter
                    logger.warning(f"Discord server error {e.status}, retrying after {wait_time:.1f}s (attempt {attempt+1})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Client error, don't retry
                    raise e
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"API call failed, retrying after {wait_time:.1f}s (attempt {attempt+1}): {e}")
                await asyncio.sleep(wait_time)
        
        raise Exception(f"API call failed after {max_retries} attempts")

    def _get_draft_channel(self, draft: DraftSession):
        """Get the channel where draft messages should be sent (thread if exists, otherwise main channel)"""
        if draft.thread_id and self.bot:
            # Try to get the thread first
            thread = self.bot.get_channel(draft.thread_id)
            if thread:
                return thread
        
        # Fall back to main channel
        if self.bot:
            return self.bot.get_channel(draft.channel_id)
        return None


class TeamCompositionChoiceView(discord.ui.View):
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.add_item(ManualTeamSelectionButton())
        self.add_item(AutoBalanceButton('simple'))


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
        user_id = interaction.user.id
        if (view.draft.is_test_mode and user_id == view.draft.real_user_id) or user_id in view.draft.captains:
            await interaction.response.send_message(f"🤖 AI 자동 구성 ({self.algorithm})을 선택했어!", ephemeral=True)
            await view.bot_commands._perform_automatic_team_balancing(view.draft, self.algorithm)
        else:
            await interaction.response.send_message("팀장만 팀 구성 방법을 선택할 수 있어.", ephemeral=True)

    # -------------------------
    # Join-based draft start
    # -------------------------
    @commands.command(
        name="페어시작",
        help="버튼으로 참가를 받아 드래프트를 시작해. 사용법: 뮤 페어시작 <총인원수:짝수> (예: 12)",
        brief="드래프트 참가 모집",
        aliases=["draft_join_start"],
        description="뮤 페어시작 12 처럼 입력하면 참가 버튼이 있는 메시지를 보내. 인원이 차면 팀장 투표로 진행돼."
    )
    async def draft_start_join_chat(self, ctx: commands.Context, total_players: int = 12) -> None:
        if total_players % 2 != 0 or total_players <= 0:
            await self.send_error(ctx, "총 인원수는 2의 배수여야 해")
            return
        if total_players // 2 not in [2, 3, 5, 6]:
            await self.send_error(ctx, "팀 크기는 2,3,5,6 중 하나여야 해 (예: 12, 6v6)")
            return
        channel_id = ctx.channel.id
        guild_id = ctx.guild.id if ctx.guild else 0
        if channel_id in self.active_drafts:
            await self.send_error(ctx, "이미 진행 중인 드래프트가 있어.")
            return
        team_size = total_players // 2
        draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
        draft.started_by_user_id = ctx.author.id
        draft.join_target_total_players = total_players
        self.active_drafts[channel_id] = draft
        self.draft_start_times[channel_id] = time.time()

        embed = discord.Embed(
            title=f"🏁 드래프트 참가 모집 ({team_size}v{team_size})",
            description="아래 버튼을 눌러 참가하거나 취소해. 인원이 차면 자동으로 진행돼.",
            color=INFO_COLOR,
        )
        embed.add_field(name="필요 인원", value=f"{len(draft.join_user_ids)}/{total_players}")
        embed.add_field(name="참가자", value="없음", inline=False)

        view = JoinDraftView(draft, self)
        self._register_view(channel_id, view)
        msg = await ctx.send(embed=embed, view=view)
        draft.join_message_id = msg.id

    async def _final_cleanup_after_outcome(self, draft: DraftSession) -> None:
        channel_id = draft.channel_id
        # Audit log
        self._audit_log("draft_outcome_recorded", draft.started_by_user_id or 0, {
            "channel_id": channel_id
        })
        # Stop views and cleanup
        await self._cleanup_views(channel_id)
        await self._cleanup_all_message_ids(draft)
        if channel_id in self.active_drafts:
            del self.active_drafts[channel_id]
        if channel_id in self.draft_start_times:
            del self.draft_start_times[channel_id]
        logger.info(f"Draft in channel {channel_id} cleaned up after outcome")

    async def _finalize_join_and_start(self, draft: DraftSession, starter_interaction: Optional[discord.Interaction] = None) -> None:
        # Build player list from joined users
        guild = None
        channel = self.bot.get_channel(draft.channel_id) if self.bot else None
        if channel and hasattr(channel, 'guild'):
            guild = channel.guild
        players: List[Tuple[int, str]] = []
        for uid in list(draft.join_user_ids)[: (draft.join_target_total_players or len(draft.join_user_ids))]:
            name = str(uid)
            if guild:
                member = guild.get_member(uid)
                if member:
                    name = member.display_name
            players.append((uid, self._sanitize_username(name)))
        # Validate count
        need = draft.join_target_total_players or 0
        if len(players) < 2 or len(players) % 2 != 0 or (need and len(players) != need):
            # Allow force start with nearest even count if force-started by permissioned user
            if len(players) < 2 or len(players) % 2 != 0:
                return
        # Convert to existing flow by populating draft.players and proceeding to captain voting
        for user_id, username in players:
            draft.players[user_id] = Player(user_id=user_id, username=username)
        # Remove join view
        try:
            if draft.join_message_id and channel:
                msg = await channel.fetch_message(draft.join_message_id)
                await msg.edit(view=None)
        except Exception:
            pass
        draft.join_target_total_players = None
        # Create thread and continue
        await self._create_draft_thread(draft)
        await self._start_captain_voting(None, draft)

    def _audit_log(self, action: str, user_id: int, data: Dict = None) -> None:
        """Simple audit logging"""
        log_entry = {
            "timestamp": time.time(),
            "action": action,
            "user_id": user_id,
            "data": data or {}
        }
        
        self.audit_logs.append(log_entry)
        
        # Keep only recent logs to prevent memory growth
        if len(self.audit_logs) > self.max_audit_logs:
            self.audit_logs = self.audit_logs[-self.max_audit_logs:]
        
        # Also log to standard logger for persistent storage
        logger.info(f"AUDIT: {action} by {user_id} - {data}")

    def _has_admin_permission(self, ctx_or_interaction: CommandContext) -> bool:
        """Check if user has admin permissions for hidden commands"""
        user_id = self.get_user_id(ctx_or_interaction)
        
        # Get member object
        if hasattr(ctx_or_interaction, 'user'):  # Interaction
            member = ctx_or_interaction.user
            if hasattr(ctx_or_interaction, 'guild') and ctx_or_interaction.guild:
                member = ctx_or_interaction.guild.get_member(user_id)
        else:  # Context
            member = ctx_or_interaction.author
        
        return member and member.guild_permissions.manage_messages

    async def _safe_api_call(self, call_func, bucket: str = "default", max_retries: int = 3):
        """Safely make Discord API calls with rate limiting and retry logic"""
        
        for attempt in range(max_retries):
            try:
                # Check rate limit bucket
                current_time = time.time()
                last_call = self.rate_limit_buckets.get(bucket, 0)
                call_count = self.api_call_counts.get(bucket, 0)
                
                # Reset call count every minute
                if current_time - last_call > 60:
                    self.api_call_counts[bucket] = 0
                    call_count = 0
                
                # Rate limit: max 50 calls per minute per bucket
                if call_count >= 50:
                    wait_time = 60 - (current_time - last_call)
                    if wait_time > 0:
                        logger.info(f"Rate limiting bucket '{bucket}', waiting {wait_time:.1f}s")
                        await asyncio.sleep(wait_time)
                        self.api_call_counts[bucket] = 0
                
                # Update counters
                self.rate_limit_buckets[bucket] = current_time
                self.api_call_counts[bucket] = call_count + 1
                
                # Make the API call
                return await call_func()
                
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else (2 ** attempt)
                    logger.warning(f"Discord rate limit hit, retrying after {retry_after}s (attempt {attempt+1})")
                    await asyncio.sleep(retry_after)
                    continue
                elif e.status >= 500:  # Server error
                    wait_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff with jitter
                    logger.warning(f"Discord server error {e.status}, retrying after {wait_time:.1f}s (attempt {attempt+1})")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Client error, don't retry
                    raise e
            except (asyncio.TimeoutError, discord.ConnectionClosed) as e:
                wait_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff with jitter
                logger.warning(f"Discord connection error, retrying after {wait_time:.1f}s (attempt {attempt+1}): {e}")
                await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                # Unexpected error, don't retry
                logger.error(f"Unexpected error in API call: {e}")
                raise e
        
        # All retries exhausted
        raise Exception(f"Failed to make API call after {max_retries} attempts")

    def _get_draft_channel(self, draft: DraftSession):
        """Get the channel where draft messages should be sent (thread if exists, otherwise main channel)"""
        if draft.thread_id and self.bot:
            # Try to get the thread first
            try:
                thread = self.bot.get_channel(draft.thread_id)
                if thread:
                    return thread
            except Exception as e:
                logger.warning(f"Could not get thread {draft.thread_id}: {e}")
        
        # Fallback to main channel
        if self.bot:
            return self.bot.get_channel(draft.channel_id)
        return None

    def _register_view(self, channel_id: int, view: discord.ui.View) -> None:
        """Register a view for memory management tracking"""
        if channel_id not in self.active_views:
            self.active_views[channel_id] = []
        self.active_views[channel_id].append(view)
        logger.debug(f"Registered view for channel {channel_id}. Total views: {len(self.active_views[channel_id])}")
        
        # Set timeout callback for automatic cleanup
        view.on_timeout = self._create_view_timeout_callback(channel_id, view)

    def _create_view_timeout_callback(self, channel_id: int, view: discord.ui.View):
        """Create a timeout callback for automatic view cleanup"""
        async def timeout_callback():
            try:
                if channel_id in self.active_views and view in self.active_views[channel_id]:
                    self.active_views[channel_id].remove(view)
                    logger.debug(f"Removed timed-out view from channel {channel_id}")
            except Exception as e:
                logger.warning(f"Error in view timeout callback: {e}")
        return timeout_callback

    async def _cleanup_views(self, channel_id: int) -> None:
        """Stop and cleanup all views for a channel"""
        if channel_id in self.active_views:
            views = self.active_views[channel_id]
            logger.info(f"Cleaning up {len(views)} views for channel {channel_id}")
            
            for view in views:
                try:
                    if not view.is_finished():
                        view.stop()
                        logger.debug(f"Stopped view: {type(view).__name__}")
                except Exception as e:
                    logger.warning(f"Error stopping view {type(view).__name__}: {e}")
            
            # Clear the list
            del self.active_views[channel_id]
            logger.info(f"Completed view cleanup for channel {channel_id}")

    async def _cleanup_all_message_ids(self, draft: DraftSession) -> None:
        """Clean up all message IDs and cancel running tasks to prevent memory leaks"""
        # Cancel all running background tasks
        for task in draft.running_tasks:
            if not task.done():
                task.cancel()
        draft.running_tasks.clear()
        
        # Clean up message IDs
        draft.captain_vote_message_id = None
        draft.captain_voting_progress_message_id = None
        draft.status_message_id = None
        draft.ban_progress_message_id = None
        draft.selection_progress_message_id = None
        draft.selection_buttons_message_id = None
        draft.last_progress_update_hash = None
        draft.last_voting_progress_hash = None
        logger.debug(f"Cleaned up all message IDs and cancelled tasks for channel {draft.channel_id}")

    async def _create_draft_thread(self, draft: DraftSession) -> Optional[discord.Thread]:
        """Create a thread for the draft"""
        try:
            main_channel = self.bot.get_channel(draft.channel_id)
            if not main_channel or not hasattr(main_channel, 'create_thread'):
                logger.warning(f"Cannot create thread in channel {draft.channel_id}")
                return None
            
            team_format = f"{draft.team_size}v{draft.team_size}"
            
            # Generate unique thread name with numbering
            base_name = f"팀 드래프트 ({team_format})"
            thread_name = f"🏆 {base_name}"
            
            # Check for existing threads with similar names and add numbering
            try:
                # Get all active threads in the channel
                active_threads = []
                async for thread in main_channel.archived_threads(limit=100):
                    active_threads.append(thread)
                
                # Also check current active threads
                if hasattr(main_channel, 'threads'):
                    active_threads.extend(main_channel.threads)
                
                # Find existing draft threads and determine next number
                existing_numbers = []
                for thread in active_threads:
                    if base_name in thread.name:
                        # Extract number from thread name if it exists
                        import re
                        match = re.search(rf"{re.escape(base_name)} #(\d+)", thread.name)
                        if match:
                            existing_numbers.append(int(match.group(1)))
                        elif thread.name == f"🏆 {base_name}":
                            existing_numbers.append(1)  # Original thread is #1
                
                # Determine next available number
                if existing_numbers:
                    next_number = max(existing_numbers) + 1
                    thread_name = f"🏆 {base_name} #{next_number}"
                
            except Exception as e:
                logger.warning(f"Could not check existing threads for numbering: {e}")
                # Fallback to timestamp-based naming if thread enumeration fails
                timestamp = int(time.time()) % 10000  # Last 4 digits of timestamp
                thread_name = f"🏆 {base_name} #{timestamp}"
            
            # Create the thread
            thread = await main_channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread,
                reason="Team draft session"
            )
            
            draft.thread_id = thread.id
            logger.info(f"Created draft thread {thread.id} in channel {draft.channel_id}")
            
            # Send welcome message to thread
            welcome_embed = discord.Embed(
                title=f"🏆 팀 드래프트 시작! ({team_format})",
                description="이 스레드에서 드래프트가 진행될거야.\n"
                           "참가자들은 여기서 드래프트 인터페이스를 사용해줘.",
                color=INFO_COLOR
            )
            
            player_list = "\n".join([f"• {player.username}" 
                                   for player in draft.players.values()])
            welcome_embed.add_field(name="참가자", value=player_list, inline=False)
            
            await self._safe_api_call(
                lambda: thread.send(embed=welcome_embed),
                bucket=f"thread_welcome_{thread.id}"
            )
            
            return thread
            
        except Exception as e:
            logger.error(f"Failed to create draft thread: {e}")
            return None

    async def _send_to_both_channels(self, draft: DraftSession, embed: discord.Embed = None, content: str = None, view: discord.ui.View = None) -> None:
        """Send message to both thread and main channel"""
        try:
            # Send to thread first
            thread = self._get_draft_channel(draft) if draft.thread_id else None
            main_channel = self.bot.get_channel(draft.channel_id) if self.bot else None
            
            if thread and draft.thread_id:
                try:
                    await self._safe_api_call(
                        lambda: thread.send(embed=embed, content=content, view=view),
                        bucket=f"thread_message_{draft.thread_id}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send to thread: {e}")
            
            # Send to main channel (without view to avoid duplicate interactions)
            if main_channel and thread:  # Only send to main if thread exists (hybrid mode)
                try:
                    await self._safe_api_call(
                        lambda: main_channel.send(embed=embed, content=content),
                        bucket=f"main_channel_message_{draft.channel_id}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send to main channel: {e}")
                    
        except Exception as e:
            logger.error(f"Error in _send_to_both_channels: {e}")

    async def _announce_team_selection_hybrid_mode(self, draft: DraftSession) -> None:
        """Announce that non-captains can leave thread during team selection"""
        try:
            # Get captain names
            captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
            
            # Send announcement to thread
            thread = self._get_draft_channel(draft) if draft.thread_id else None
            if thread:
                thread_embed = discord.Embed(
                    title="📢 팀 선택 단계 시작",
                    description=f"이제 **{' vs '.join(captain_names)}** 팀장들이 팀원을 선택할 차례야.\n\n"
                               f"**📤 팀장이 아닌 플레이어들은 이제 스레드를 나가서 메인 채널에서 자유롭게 채팅해도 돼!**\n"
                               f"팀 선택 과정과 결과는 메인 채널에도 업데이트될거야.",
                    color=INFO_COLOR
                )
                await self._safe_api_call(
                    lambda: thread.send(embed=thread_embed),
                    bucket=f"team_selection_announce_{draft.thread_id}"
                )
            
            # Send announcement to main channel
            main_channel = self.bot.get_channel(draft.channel_id) if self.bot else None
            if main_channel:
                main_embed = discord.Embed(
                    title="⚡ 팀 선택 단계 진입",
                    description=f"드래프트가 팀 선택 단계로 진입했어!\n\n"
                               f"🎯 **팀장**: {' vs '.join(captain_names)}\n"
                               f"📍 **진행 위치**: 드래프트 스레드\n"
                               f"📊 **업데이트**: 이 채널에서도 진행 상황을 볼 수 있어",
                    color=SUCCESS_COLOR
                )
                await self._safe_api_call(
                    lambda: main_channel.send(embed=main_embed),
                    bucket=f"team_selection_main_announce_{draft.channel_id}"
                )
                
        except Exception as e:
            logger.error(f"Error announcing team selection hybrid mode: {e}")



    async def _add_reopen_captain_ban_interface_button(self, draft: DraftSession, captain_id: int) -> None:
        """Add reopen interface button to captain ban progress message"""
        try:
            if draft.ban_progress_message_id:
                # Use thread if available, otherwise main channel
                channel = self._get_draft_channel(draft)
                if channel:
                    message = await channel.fetch_message(draft.ban_progress_message_id)
                    if message:
                        # Create a view with just the reopen button for this captain
                        view = ReopenCaptainBanInterfaceView(draft, self, captain_id)
                        self._register_view(draft.channel_id, view)
                        await message.edit(view=view)
        except Exception as e:
            logger.error(f"Error adding reopen captain ban interface button: {e}")

    async def _add_reopen_selection_interface_button(self, draft: DraftSession, user_id: int) -> None:
        """Add generic reopen interface button to selection progress message"""
        try:
            if draft.selection_progress_message_id:
                # Use thread if available, otherwise main channel
                channel = self._get_draft_channel(draft)
                if channel:
                    message = await channel.fetch_message(draft.selection_progress_message_id)
                    if message:
                        # Create a view with generic reopen button (single button for all users)
                        view = GenericReopenSelectionView(draft, self)
                        self._register_view(draft.channel_id, view)
                        await message.edit(view=view)
        except Exception as e:
            logger.error(f"Error adding reopen selection interface button: {e}")

    @commands.command(
        name="페어",
        help="팀 드래프트를 시작해 (기본: 6v6, 지원: 2v2/3v3/5v5/6v6)",
        brief="팀 드래프트 시작",
        aliases=["draft", "팀드래프트"],
        description="팀 드래프트 시스템을 시작해.\n"
                   "사용법: 뮤 페어 @모든참가자들 [team_size:숫자] [captains:@팀장1 @팀장2]\n"
                   "⚠️ 중요: 팀장도 참가자 목록에 포함되어야 해!\n"
                   "예시: 뮤 페어 @user1 @user2 @user3 @user4 (2v2 드래프트)\n"
                   "예시: 뮤 페어 @user1 @user2 @user3 @user4 captains:@user1 @user3 (팀장 지정)\n"
                   "예시: 뮤 페어 team_size:3 (3v3 드래프트)\n"
                   "예시: 뮤 페어 team_size:5 (5v5 드래프트)"
    )
    async def draft_start_chat(self, ctx: commands.Context, *, args: str = "") -> None:
        """Start team draft via chat command"""
        # Legacy quick auto-draft disabled; proceed with interactive flow

        # Parse test_mode and team_size from args
        test_mode = "test_mode:true" in args.lower() or "test_mode=true" in args.lower()
        
        # Parse team_size (default 6 for 6v6)
        team_size = 6  # default
        if "team_size:2" in args.lower() or "team_size=2" in args.lower():
            team_size = 2
        elif "team_size:3" in args.lower() or "team_size=3" in args.lower():
            team_size = 3
        elif "team_size:5" in args.lower() or "team_size=5" in args.lower():
            team_size = 5
        elif "team_size:6" in args.lower() or "team_size=6" in args.lower():
            team_size = 6
        
        # Parse captains from args (look for captains: keyword)
        captains_str = ""
        players_str = args  # Start with full args
        import re
        # More robust regex that handles various spacing and formatting
        captains_match = re.search(r'captains:\s*(<@!?\d+>\s*<@!?\d+>)', args, re.IGNORECASE)
        if captains_match:
            captains_str = captains_match.group(1)
            # Remove the entire captains portion from players_str to avoid double-counting
            players_str = re.sub(r'captains:\s*<@!?\d+>\s*<@!?\d+>', '', args, flags=re.IGNORECASE).strip()
            logger.info(f"Parsed captains: '{captains_str}', remaining players: '{players_str}'")
            
        # Pass the cleaned players_str to avoid counting captains twice
        await self._handle_draft_start(ctx, players_str, test_mode, team_size, captains_str)

    async def _handle_auto_draft_quick(self, ctx: commands.Context, args: str, use_predictor: bool = False) -> None:
        # Legacy path removed in favor of the new AI balancing integrated flow
        await self.send_error(ctx, "이 기능은 더 이상 지원되지 않아. 새 AI 드래프트를 사용해줘.")



    @commands.command(
        name="페어결과",
        help="최근 드래프트 경기의 결과를 기록합니다 (관리자/팀장 추천)",
        brief="드래프트 결과 기록",
        description="사용법: 뮤 페어결과 <승리팀:1|2> [점수]"
    )
    async def record_match_result_prefix(self, ctx: commands.Context, winner: int, score: str = "") -> None:
        try:
            await self._handle_record_result(ctx, winner, score)
        except Exception as e:
            logger.error(f"record_match_result_prefix failed: {e}")
            await self.send_error(ctx, "결과 기록 중 문제가 발생했어")



    @command_handler()
    async def _handle_record_result(self, ctx_or_interaction: CommandContext, winner: int, score: str = "") -> None:
        # Prevent duplicates: if an active draft exists and outcome already recorded, block
        try:
            channel_id_active = self.get_channel_id(ctx_or_interaction)
            draft_active = self.active_drafts.get(channel_id_active)
            if draft_active and draft_active.outcome_recorded:
                await self.send_error(ctx_or_interaction, "이미 결과가 기록되었어")
                return
        except Exception:
            pass

        if winner not in (1, 2):
            await self.send_error(ctx_or_interaction, "승리 팀은 1 또는 2여야 해")
            return

        # Use the most recently completed draft for this channel
        channel_id = self.get_channel_id(ctx_or_interaction)
        guild_id = self.get_guild_id(ctx_or_interaction) or 0

        # Construct the same match_id format used in prematch logging
        # Note: prematch was recorded at completion time with epoch seconds; we cannot know exact seconds here,
        # so we append an outcome entry that includes only match_id prefix (guild_id:channel_id), which consumers
        # can match to the latest prematch in that channel.
        match_id_prefix = f"{guild_id}:{channel_id}:"

        try:
            # Append an outcome entry tagged with the channel/guild prefix; training code can resolve to latest
            self.match_recorder.write_outcome(match_id=match_id_prefix, winner=winner, score=score or None)
            # Mark recorded if active draft exists
            try:
                if draft_active:
                    draft_active.outcome_recorded = True
            except Exception:
                pass
            await self.send_success(ctx_or_interaction, "경기 결과를 기록했어")
        except Exception as e:
            logger.error(f"Failed to write outcome: {e}")
            await self.send_error(ctx_or_interaction, "결과를 저장할 수가 없네")

    # Roster management commands moved to src/commands/roster_management.py



    @commands.command(
        name="페어시뮬",
        help="팀장이 양 팀을 모두 구성하는 시뮬레이션 드래프트를 시작합니다 (기본 6v6)",
        brief="시뮬 드래프트",
        description="사용법: 뮤 페어시뮬 [team_size:숫자] [players:@...]")
    async def draft_simulate_prefix(self, ctx: commands.Context, *, args: str = "") -> None:
        await self._handle_simulation_start(ctx, args)

    @app_commands.command(name="페어시뮬", description="팀장이 양 팀을 모두 구성하는 시뮬레이션 드래프트를 시작합니다")
    async def draft_simulate_slash(self, interaction: discord.Interaction, players: str = "", team_size: int = 6) -> None:
        await self._handle_simulation_start(interaction, f"{players} team_size:{team_size}")

    @command_handler()
    async def _handle_simulation_start(self, ctx_or_interaction: CommandContext, args: str = "") -> None:
        # Parse team_size (default 6)
        team_size = 6
        lowered = args.lower()
        if "team_size:2" in lowered or "team_size=2" in lowered:
            team_size = 2
        elif "team_size:3" in lowered or "team_size=3" in lowered:
            team_size = 3
        elif "team_size:5" in lowered or "team_size=5" in lowered:
            team_size = 5
        elif "team_size:6" in lowered or "team_size=6" in lowered:
            team_size = 6

        # Collect players: prefer explicit mentions, else use saved guild roster
        players_str = args
        parsed_players = await self._parse_players(ctx_or_interaction, players_str)
        real_user_id = self.get_user_id(ctx_or_interaction)
        real_username = self.get_user_name(ctx_or_interaction)

        if not parsed_players:
            # Fallback to guild roster; prioritize players with preferred servants to limit combinations
            guild_id = self.get_guild_id(ctx_or_interaction)
            roster = self.roster_store.load(guild_id or 0)
            # Sort: those with any preferred_servants first
            roster_sorted = sorted(roster, key=lambda rp: 0 if getattr(rp, 'preferred_servants', []) else 1)
            parsed_players = [(p.user_id, p.display_name) for p in roster_sorted]
            # Ensure invoker is in the roster
            if real_user_id not in {uid for uid, _ in parsed_players}:
                parsed_players.insert(0, (real_user_id, real_username))
        else:
            # Ensure invoker included when mentions exist
            user_ids = {uid for uid, _ in parsed_players}
            if real_user_id not in user_ids:
                parsed_players.insert(0, (real_user_id, real_username))

        # Create draft in test mode where the real user can act as both captains
        channel_id = self.get_channel_id(ctx_or_interaction)
        guild_id = self.get_guild_id(ctx_or_interaction)
        if channel_id in self.active_drafts:
            await self.send_error(ctx_or_interaction, "이미 진행 중인 드래프트가 있어.")
            return

        draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
        draft.is_test_mode = True
        draft.real_user_id = real_user_id

        # Register players
        for uid, uname in parsed_players:
            draft.players[uid] = Player(user_id=uid, username=uname)

        # Set real user as both captains logically by letting them act as any captain
        # We will pick two captains automatically if not enough players
        all_ids = list(draft.players.keys())
        if len(all_ids) < 2:
            await self.send_error(ctx_or_interaction, "플레이어가 부족해")
            return
        draft.captains = [real_user_id, real_user_id]  # Logical: same user can act for both

        # Proceed to servant ban/selection like normal; test mode allows real user to do all actions
        draft.is_simulation = True
        # Tag simulation session ID and author to allow cross-captain comparison later
        # Session ID groups independent runs for the same scenario if provided in args, else timestamp-based
        import re
        session_match = re.search(r"session:(\S+)", args, re.IGNORECASE)
        session_id = session_match.group(1) if session_match else str(int(time.time()))
        draft.simulation_session_id = session_id
        draft.simulation_author_id = real_user_id
        self.active_drafts[channel_id] = draft
        await self.send_success(ctx_or_interaction, f"시뮬레이션 드래프트를 시작했어 ({team_size}v{team_size}).")
        # Use the normal flow: start servant ban (system bans + captains)
        await self._start_servant_ban_phase(draft)

    @command_handler()
    async def _handle_draft_start(
        self,
        ctx_or_interaction: CommandContext,
        players_str: str = "",
        test_mode: bool = False,
        team_size: int = 6,
        captains_str: str = ""
    ) -> None:
        """Handle draft start command"""
        try:
            channel_id = self.get_channel_id(ctx_or_interaction)
            guild_id = self.get_guild_id(ctx_or_interaction)
            
            if channel_id in self.active_drafts:
                await self.send_error(ctx_or_interaction, "이미 진행 중인 드래프트가 있어.")
                return
                
            if not guild_id:
                await self.send_error(ctx_or_interaction, "서버에서만 드래프트를 시작할 수 있어.")
                return
            
            # Handle test mode or real players
            if test_mode:
                players = await self._generate_test_players(ctx_or_interaction, team_size)
                team_format = f"{team_size}v{team_size}"
                await self.send_success(
                    ctx_or_interaction, 
                    #f"🧪 **테스트 모드 ({team_format})**로 드래프트를 시작해!\n"
                    f"가상 플레이어 {team_size * 2}명을 자동으로 생성했어."
                )
            else:
                # Parse player mentions
                players = await self._parse_players(ctx_or_interaction, players_str)
                
                total_players_needed = team_size * 2  # Total players for both teams
                if len(players) != total_players_needed:
                    # Check if the user might have double-counted captains
                    captain_note = ""
                    if captains_str and len(players) == total_players_needed + 2:
                        captain_note = "\n💡 **팁**: 팀장은 참가자 목록에 이미 포함되어야 해. 팀장을 별도로 추가하지 말고 기존 참가자 중에서 지정해줘."
                    
                    await self.send_error(
                        ctx_or_interaction, 
                        f"정확히 {total_players_needed}명의 플레이어가 필요해. (현재: {len(players)}명){captain_note}"
                    )
                    return
            
            # Parse pre-assigned captains if provided
            pre_assigned_captains = []
            if captains_str.strip() and not test_mode:  # Don't use pre-assigned captains in test mode
                try:
                    captain_mentions = await self._parse_captains(ctx_or_interaction, captains_str)
                    if len(captain_mentions) != 2:
                        await self.send_error(
                            ctx_or_interaction, 
                            f"정확히 2명의 팀장을 지정해야 해. (현재: {len(captain_mentions)}명)"
                        )
                        return
                    
                    # Validate that all captains are in the player list
                    player_ids = {user_id for user_id, _ in players}
                    for captain_id, captain_name in captain_mentions:
                        if captain_id not in player_ids:
                            await self.send_error(
                                ctx_or_interaction, 
                                f"팀장 {captain_name}은(는) 참가자 목록에 없어. 먼저 참가자로 추가해줘."
                            )
                            return
                    
                    pre_assigned_captains = [captain_id for captain_id, _ in captain_mentions]
                    
                except Exception as e:
                    await self.send_error(
                        ctx_or_interaction, 
                        f"팀장 지정 처리 중 오류가 발생했어: {str(e)}"
                    )
                    return
            
            # Create draft session
            draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
            draft.started_by_user_id = self.get_user_id(ctx_or_interaction)
            
            # Set test mode flag and real user if in test mode
            if test_mode:
                draft.is_test_mode = True
                draft.real_user_id = self.get_user_id(ctx_or_interaction)
            
            for user_id, username in players:
                sanitized_username = self._sanitize_username(username)
                is_captain = user_id in pre_assigned_captains
                draft.players[user_id] = Player(user_id=user_id, username=sanitized_username, is_captain=is_captain)
            
            # Set captains if pre-assigned
            if pre_assigned_captains:
                draft.captains = pre_assigned_captains
                # Initialize captain ban progress tracking
                for captain_id in draft.captains:
                    draft.captain_ban_progress[captain_id] = False
            
            self.active_drafts[channel_id] = draft
            self.draft_start_times[channel_id] = time.time()  # Record start time
            
            # Audit log
            self._audit_log("draft_start", self.get_user_id(ctx_or_interaction), {
                "channel_id": channel_id,
                "team_size": team_size,
                "test_mode": test_mode,
                "players_count": len(players)
            })
            
            # Create draft thread for clean environment
            thread = await self._create_draft_thread(draft)
            
            # Send summary message to main channel with thread link
            team_format = f"{team_size}v{team_size}"
            main_channel = self.bot.get_channel(channel_id) if self.bot else None
            
            if thread and main_channel:
                summary_embed = discord.Embed(
                    title=f"🏆 팀 드래프트 시작됨! ({team_format})",
                    description=f"드래프트는 {thread.mention}에서 진행돼.\n"
                               f"참가자들은 스레드로 이동해서 드래프트에 참여해줘!",
                    color=SUCCESS_COLOR
                )
                
                if test_mode:
                    summary_embed.add_field(
                        name="🧪 테스트 모드", 
                        value="가상 플레이어들과 함께 테스트 중이야.", 
                        inline=False
                    )
                
                if pre_assigned_captains:
                    captain_names = [draft.players[cap_id].username for cap_id in pre_assigned_captains]
                    summary_embed.add_field(
                        name="👑 지정된 팀장", 
                        value=f"{' vs '.join(captain_names)} (투표 생략)", 
                        inline=False
                    )
                
                await self._safe_api_call(
                    lambda: main_channel.send(embed=summary_embed),
                    bucket=f"draft_summary_{channel_id}"
                )
            
            # Start captain voting or skip if captains are pre-assigned
            if pre_assigned_captains:
                # Skip voting and go directly to servant ban phase
                draft.phase = DraftPhase.SERVANT_BAN
                await self._start_servant_ban_phase(draft)
            else:
                # Start captain voting (now in thread)
                await self._start_captain_voting(ctx_or_interaction, draft)
            
        except Exception as e:
            logger.error(f"Error starting draft: {e}")
            await self.send_error(ctx_or_interaction, "드래프트 시작 중 문제가 생겼어.")

    async def _generate_test_players(self, ctx_or_interaction: CommandContext, team_size: int) -> List[Tuple[int, str]]:
        """Generate fake players for testing"""
        # Get the real user who started the test
        real_user_id = self.get_user_id(ctx_or_interaction)
        real_username = self.get_user_name(ctx_or_interaction)
        
        # Famous character names for test players
        test_names = [
            "알트리아", "길가메시", "쿠훌린", "메두사", "메데이아", 
            "허산", "헤라클레스", "이스칸다르", "아르토리아", "엠브레인",
            "잔 다르크", "오지만디아스", "스카하", "마슈", "네로"
        ]
        
        players = []
        total_players = team_size * 2  # Total players needed
        
        # Add the real user as first player
        players.append((real_user_id, real_username))
        
        # Generate fake players with fake IDs
        for i in range(total_players - 1):  # -1 because we already added the real user
            fake_id = random.randint(100000000000000000, 999999999999999999)  # 18-digit Discord-like ID
            fake_name = test_names[i] if i < len(test_names) else f"테스트플레이어{i+1}"
            players.append((fake_id, fake_name))
        
        return players

    async def _parse_players(
        self,
        ctx_or_interaction: CommandContext,
        players_str: str
    ) -> List[Tuple[int, str]]:
        """Parse player mentions from string"""
        players = []
        
        # Extract user mentions from string
        import re
        mention_pattern = r'<@!?(\d+)>'
        mentions = re.findall(mention_pattern, players_str)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
        else:
            guild = ctx_or_interaction.guild
            
        if not guild:
            raise ValueError("Guild not found")
        
        for user_id_str in mentions:
            user_id = int(user_id_str)
            member = guild.get_member(user_id)
            if member:
                players.append((user_id, member.display_name))
        
        return players

    async def _parse_captains(
        self,
        ctx_or_interaction: CommandContext,
        captains_str: str
    ) -> List[Tuple[int, str]]:
        """Parse captain mentions from string"""
        captains = []
        
        # Extract user mentions from string
        import re
        mention_pattern = r'<@!?(\d+)>'
        mentions = re.findall(mention_pattern, captains_str)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
        else:
            guild = ctx_or_interaction.guild
            
        if not guild:
            raise ValueError("Guild not found")
        
        for user_id_str in mentions:
            user_id = int(user_id_str)
            member = guild.get_member(user_id)
            if member:
                captains.append((user_id, member.display_name))
        
        return captains

    async def _start_captain_voting(
        self,
        ctx_or_interaction: CommandContext,
        draft: DraftSession
    ) -> None:
        """Start the captain voting phase"""
        
        draft.phase = DraftPhase.CAPTAIN_VOTING
        
        # Initialize voting progress tracking
        for user_id in draft.players.keys():
            draft.captain_voting_progress[user_id] = 0  # Number of votes cast
        # Logging: captain voting start snapshot
        try:
            player_snapshot = ", ".join(
                f"{player.user_id}:{player.username}" for player in draft.players.values()
            )
            logger.info(f"[CaptainVote] phase_start channel={draft.channel_id} players=[{player_snapshot}]")
        except Exception:
            logger.info(f"[CaptainVote] phase_start channel={draft.channel_id} players_snapshot_error")
        
        # Start the timer
        draft.captain_voting_start_time = time.monotonic()
        
        embed = discord.Embed(
            title="🎖️ 팀장 선출 투표",
            description="모든 플레이어는 팀장으로 추천하고 싶은 2명에게 투표해.\n"
                       "가장 많은 표를 받은 2명이 팀장이 돼.\n"
                       f"⏰ 제한 시간: {draft.captain_voting_time_limit // 60}분 {draft.captain_voting_time_limit % 60}초",
            color=INFO_COLOR
        )
        
        player_list = "\n".join([f"{i+1}. {player.username}" 
                                for i, player in enumerate(draft.players.values())])
        embed.add_field(name="참가자 목록", value=player_list, inline=False)
        embed.add_field(name="투표 방법", value="아래 번호 버튼을 눌러 투표해", inline=False)
        
        # Create voting view
        view = CaptainVotingView(draft, self)
        self._register_view(draft.channel_id, view)
        
        # Send to draft thread if available, otherwise use the original interaction context
        draft_channel = self._get_draft_channel(draft)
        
        if draft_channel and draft.thread_id:
            # Send to thread
            message = await self._safe_api_call(
                lambda: draft_channel.send(embed=embed, view=view),
                bucket=f"captain_voting_{draft.channel_id}"
            )
        else:
            # Fallback to original interaction context
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    message = await self._safe_api_call(
                        lambda: ctx_or_interaction.followup.send(embed=embed, view=view),
                        bucket=f"captain_voting_{draft.channel_id}"
                    )
                else:
                    await self._safe_api_call(
                        lambda: ctx_or_interaction.response.send_message(embed=embed, view=view),
                        bucket=f"captain_voting_{draft.channel_id}"
                    )
                    message = await ctx_or_interaction.original_response()
            else:
                message = await self._safe_api_call(
                    lambda: ctx_or_interaction.send(embed=embed, view=view),
                    bucket=f"captain_voting_{draft.channel_id}"
                )
        
        draft.captain_vote_message_id = message.id
        
        # Send separate progress message (similar to servant selection)
        progress_embed = discord.Embed(
            title="📊 투표 진행 상황",
            description="각 플레이어의 투표 진행 상황을 실시간으로 표시해.",
            color=INFO_COLOR
        )
        
        await self._update_captain_voting_progress_embed(draft, progress_embed)
        
        if draft_channel:
            try:
                progress_message = await self._safe_api_call(
                    lambda: draft_channel.send(embed=progress_embed), 
                    bucket=f"captain_voting_progress_{draft.channel_id}"
                )
                draft.captain_voting_progress_message_id = progress_message.id
                logger.info(f"Created captain voting progress message {progress_message.id}")
            except Exception as e:
                logger.error(f"Failed to send captain voting progress message: {e}")
        
        # Start background timer task
        task = asyncio.create_task(self._captain_voting_timer(draft))
        draft.running_tasks.add(task)
        task.add_done_callback(draft.running_tasks.discard)

    async def _update_captain_voting_progress_embed(self, draft: DraftSession, embed: discord.Embed) -> None:
        """Update captain voting progress in the embed"""
        
        progress_text = ""
        completed_count = 0
        
        for user_id, player in draft.players.items():
            votes_cast = draft.captain_voting_progress.get(user_id, 0)
            status = f"✅ 완료 ({votes_cast}/2)" if votes_cast >= 2 else f"⏳ 진행 중 ({votes_cast}/2)"
            progress_text += f"{player.username}: {status}\n"
            if votes_cast >= 2:
                completed_count += 1
        
        total_players = len(draft.players)
        embed.add_field(
            name=f"진행 상황 ({completed_count}/{total_players})",
            value=progress_text.strip(),
            inline=False
        )
        


    async def _update_captain_voting_progress_message(self, draft: DraftSession) -> None:
        """Update the captain voting progress message"""
        if not draft.captain_voting_progress_message_id:
            return
            
        channel = self._get_draft_channel(draft)
        if not channel:
            return
            
        try:
            # Create hash of current progress to detect changes
            progress_hash = hash(frozenset(draft.captain_voting_progress.items()))
            
            # Skip update if progress hasn't changed
            if hasattr(draft, 'last_voting_progress_hash') and draft.last_voting_progress_hash == str(progress_hash):
                return
                
            draft.last_voting_progress_hash = str(progress_hash)
            
            message = await channel.fetch_message(draft.captain_voting_progress_message_id)
            
            # Create progress-only embed
            embed = discord.Embed(
                title="📊 투표 진행 상황",
                description="각 플레이어의 투표 진행 상황을 실시간으로 표시해.",
                color=INFO_COLOR
            )
            
            await self._update_captain_voting_progress_embed(draft, embed)
            
            await message.edit(embed=embed)
            
        except discord.NotFound:
            logger.warning("Captain voting progress message not found")
        except Exception as e:
            logger.error(f"Failed to update captain voting progress message: {e}")

    async def _captain_voting_timer(self, draft: DraftSession) -> None:
        """Background task to handle captain voting timeout"""
        while draft.phase == DraftPhase.CAPTAIN_VOTING:
            if not draft.captain_voting_start_time:
                break
                
            elapsed = time.monotonic() - draft.captain_voting_start_time
            remaining = draft.captain_voting_time_limit - elapsed
            
            if remaining <= 0:
                # Time's up - find the voting view and finalize
                if draft.channel_id in self.active_views:
                    for view in self.active_views[draft.channel_id]:
                        if isinstance(view, CaptainVotingView):
                            await view._finalize_voting()
                            break
                break
                
            # Update progress every 10 seconds
            await asyncio.sleep(10)
            if draft.phase == DraftPhase.CAPTAIN_VOTING:
                await self._update_captain_voting_progress_message(draft)

    async def _servant_selection_timer(self, draft: DraftSession) -> None:
        """Background task to handle servant selection timeout"""
        while draft.phase == DraftPhase.SERVANT_SELECTION:
            if not draft.selection_start_time:
                break
                
            elapsed = time.monotonic() - draft.selection_start_time
            remaining = draft.selection_time_limit - elapsed
            
            if remaining <= 0:
                # Time's up - assign random servants to players who haven't selected
                await self._handle_selection_timeout(draft)
                break
                
            # Update progress every 10 seconds
            await asyncio.sleep(10)
            if draft.phase == DraftPhase.SERVANT_SELECTION:
                await self._update_selection_progress_message(draft)

    async def _servant_reselection_timer(self, draft: DraftSession) -> None:
        """Background task to handle servant reselection timeout"""
        while draft.phase == DraftPhase.SERVANT_RESELECTION:
            if not draft.reselection_start_time:
                break
                
            elapsed = time.monotonic() - draft.reselection_start_time
            remaining = draft.reselection_time_limit - elapsed
            
            if remaining <= 0:
                # Time's up - assign random servants to players who haven't reselected
                await self._handle_reselection_timeout(draft)
                break
                
            # Update progress every 10 seconds
            await asyncio.sleep(10)
            if draft.phase == DraftPhase.SERVANT_RESELECTION:
                await self._update_selection_progress_message(draft)

    async def _handle_selection_timeout(self, draft: DraftSession) -> None:
        """Handle servant selection timeout by assigning random servants"""
        
        # Get players who haven't completed selection
        incomplete_players = [
            user_id for user_id, completed in draft.selection_progress.items()
            if not completed
        ]
        
        if not incomplete_players:
            return  # All players completed
        
        # Get available servants (exclude banned and already selected)
        taken_servants = {
            player.selected_servant for player in draft.players.values() 
            if player.selected_servant
        }
        available_servants = list(draft.available_servants - draft.banned_servants - taken_servants)
        
        # Assign random servants to incomplete players
        for user_id in incomplete_players:
            if available_servants:
                random_servant = random.choice(available_servants)
                draft.players[user_id].selected_servant = random_servant
                draft.selection_progress[user_id] = True
                available_servants.remove(random_servant)
                logger.info(f"Auto-assigned {random_servant} to {draft.players[user_id].username} due to timeout")
        
        # Update progress and proceed to reveal
        await self._update_selection_progress_message(draft)
        await self._reveal_servant_selections(draft)

    async def _handle_reselection_timeout(self, draft: DraftSession) -> None:
        """Handle servant reselection timeout by assigning random servants"""
        
        # Get players who need to reselect but haven't completed
        conflicted_players = set()
        for user_ids in draft.conflicted_servants.values():
            conflicted_players.update(user_ids)
        
        incomplete_players = [
            user_id for user_id in conflicted_players
            if not draft.players[user_id].selected_servant
        ]
        
        if not incomplete_players:
            return  # All players completed reselection
        
        # Get available servants (exclude confirmed, banned, and already selected)
        confirmed_servants = set(draft.confirmed_servants.values())
        taken_servants = {
            player.selected_servant for player in draft.players.values() 
            if player.selected_servant and player.selected_servant not in confirmed_servants
        }
        available_servants = list(draft.available_servants - confirmed_servants - draft.banned_servants - taken_servants)
        
        # Assign random servants to incomplete players
        for user_id in incomplete_players:
            if available_servants:
                random_servant = random.choice(available_servants)
                draft.players[user_id].selected_servant = random_servant
                available_servants.remove(random_servant)
                logger.info(f"Auto-assigned {random_servant} to {draft.players[user_id].username} due to reselection timeout")
        
        # Update progress and proceed to reveal
        await self._update_selection_progress_message(draft)
        await self._check_reselection_completion(draft)

    @app_commands.command(name="페어상태", description="현재 드래프트 상태를 확인해")
    async def draft_status_slash(self, interaction: discord.Interaction) -> None:
        """Check current draft status"""
        await self._handle_draft_status(interaction)

    @commands.command(
        name="페어상태",
        help="현재 드래프트 상태를 확인해",
        brief="드래프트 상태 확인",
        aliases=["draft_status", "드래프트상태"]
    )
    async def draft_status_chat(self, ctx: commands.Context) -> None:
        """Check current draft status via chat command"""
        await self._handle_draft_status(ctx)

    @command_handler()
    async def _handle_draft_status(self, ctx_or_interaction: CommandContext) -> None:
        """Handle draft status command"""
        channel_id = self.get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_drafts:
            await self.send_error(ctx_or_interaction, "진행 중인 드래프트가 없어.")
            return
        
        draft = self.active_drafts[channel_id]
        embed = await self._create_status_embed(draft)
        await self.send_response(ctx_or_interaction, embed=embed)

    async def _create_status_embed(self, draft: DraftSession) -> discord.Embed:
        """Create status embed for current draft state"""
        team_format = f"{draft.team_size}v{draft.team_size}"
        embed = discord.Embed(title=f"🏆 드래프트 현황 ({team_format})", color=INFO_COLOR)
        
        phase_names = {
            DraftPhase.WAITING: "대기 중",
            DraftPhase.CAPTAIN_VOTING: "팀장 선출 투표",
            DraftPhase.SERVANT_BAN: "서번트 밴",
            DraftPhase.SERVANT_SELECTION: "서번트 선택",
            DraftPhase.SERVANT_RESELECTION: "서번트 재선택",
            DraftPhase.TEAM_SELECTION: "팀원 선택",
            DraftPhase.COMPLETED: "완료"
        }
        
        embed.add_field(
            name="현재 단계",
            value=phase_names.get(draft.phase, "알 수 없음"),
            inline=False
        )
        
        if draft.captains:
            captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
            embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
        
        if draft.phase in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
            confirmed_count = len(draft.confirmed_servants)
            embed.add_field(
                name="서번트 선택 진행도",
                value=f"{confirmed_count}/{draft.team_size * 2} 완료",
                inline=True
            )
        
        return embed 

    @app_commands.command(name="페어취소", description="진행 중인 드래프트를 취소해")
    async def draft_cancel_slash(self, interaction: discord.Interaction) -> None:
        """Cancel current draft"""
        await self._handle_draft_cancel(interaction)

    @commands.command(
        name="페어취소",
        help="진행 중인 드래프트를 취소해",
        brief="드래프트 취소",
        aliases=["draft_cancel", "드래프트취소"]
    )
    async def draft_cancel_chat(self, ctx: commands.Context) -> None:
        """Cancel current draft via chat command"""
        await self._handle_draft_cancel(ctx)

    @app_commands.command(name="페어테스트", description="팀 드래프트 시스템 테스트")
    async def draft_test_slash(self, interaction: discord.Interaction) -> None:
        """Test if team draft system is working"""
        logger.info(f"페어테스트 command called by {interaction.user.name}")
        await interaction.response.send_message(
            "✅ **팀 드래프트 시스템이 작동해!** (v5.0)\n\n"
            "지원하는 형식:\n"
            "• `/페어 team_size:2` - 2v2 드래프트 (4명 필요)\n"
            "• `/페어 team_size:3` - 3v3 드래프트 (6명 필요)\n"
            "• `/페어 team_size:5` - 5v5 드래프트 (10명 필요)\n"
            "• `/페어` - 6v6 드래프트 (12명 필요, 기본값)\n\n"
            "팀장 지정 기능:\n"
            "• `captains:@팀장1 @팀장2` - 팀장 수동 지정 (투표 건너뛰기)\n"
            "• ⚠️ 팀장도 참가자 목록에 포함되어야 해!\n"
            "• 예시: `뮤 페어 @user1 @user2 @user3 @user4 captains:@user1 @user3`\n\n"
            "기타 명령어:\n"
            "• `/페어상태` - 현재 드래프트 상태 확인\n"
            "• `/페어취소` - 진행 중인 드래프트 취소\n\n",
            ephemeral=True
        )

    # Hidden admin commands - not visible to regular users
    @app_commands.command(name="페어정리", description="진행 중인 드래프트를 강제로 정리해 (관리자용)")
    @app_commands.default_permissions(manage_messages=True)
    async def draft_force_cleanup_slash(self, interaction: discord.Interaction, channel_id: str = None) -> None:
        """Force cleanup a draft (admin only)"""
        await self._handle_force_cleanup(interaction, channel_id)

    @commands.command(name="페어정리", help="진행 중인 드래프트를 강제로 정리해 (관리자용)", aliases=["draft_cleanup"], hidden=True)
    @commands.has_permissions(manage_messages=True)
    async def draft_force_cleanup_chat(self, ctx: commands.Context, channel_id: str = None) -> None:
        """Force cleanup a draft (admin only)"""
        await self._handle_force_cleanup(ctx, channel_id)

    @app_commands.command(name="페어감사", description="드래프트 감사 로그 확인 (관리자용)")
    @app_commands.default_permissions(manage_messages=True)
    async def draft_audit_slash(self, interaction: discord.Interaction, limit: int = 10) -> None:
        """View audit logs (admin only)"""
        await self._handle_audit_query(interaction, limit)

    @commands.command(name="페어감사", help="드래프트 감사 로그 확인 (관리자용)", aliases=["draft_audit"], hidden=True)
    @commands.has_permissions(manage_messages=True)
    async def draft_audit_chat(self, ctx: commands.Context, limit: int = 10) -> None:
        """View audit logs (admin only)"""
        await self._handle_audit_query(ctx, limit)

    @command_handler()
    async def _handle_force_cleanup(self, ctx_or_interaction: CommandContext, channel_id_str: str = None) -> None:
        """Handle forced cleanup with permission check"""
        if not self._has_admin_permission(ctx_or_interaction):
            await self.send_error(ctx_or_interaction, "이 명령어는 메시지 관리 권한이 있는 사용자만 사용할 수 있어.")
            return
        
        user_id = self.get_user_id(ctx_or_interaction)
        
        # Determine target channel
        if channel_id_str:
            try:
                target_channel_id = int(channel_id_str)
            except ValueError:
                await self.send_error(ctx_or_interaction, "올바른 채널 ID를 입력해줘.")
                return
        else:
            target_channel_id = self.get_channel_id(ctx_or_interaction)
        
        # Check if draft exists
        if target_channel_id not in self.active_drafts:
            await self.send_error(ctx_or_interaction, f"채널 {target_channel_id}에 진행 중인 드래프트가 없어.")
            return
        
        # Get draft info for audit logging
        draft = self.active_drafts[target_channel_id]
        self._audit_log("force_cleanup", user_id, {
            "channel_id": target_channel_id,
            "draft_phase": draft.phase.value,
            "players_count": len(draft.players),
            "team_size": draft.team_size
        })
        
        # Reuse existing cleanup logic
        await self._cleanup_views(target_channel_id)
        await self._cleanup_all_message_ids(draft)
        
        # Remove from tracking
        del self.active_drafts[target_channel_id]
        if target_channel_id in self.draft_start_times:
            del self.draft_start_times[target_channel_id]
        
        # Send notification to both channels
        try:
            if self.bot:
                # Notify thread if exists
                if draft.thread_id:
                    thread = self.bot.get_channel(draft.thread_id)
                    if thread:
                        await thread.send(embed=discord.Embed(
                            title="🧹 드래프트 강제 정리됨",
                            description=f"관리자에 의해 드래프트가 정리되었어.",
                            color=INFO_COLOR
                        ))
                
                # Notify main channel
                main_channel = self.bot.get_channel(target_channel_id)
                if main_channel:
                    await main_channel.send(embed=discord.Embed(
                        title="🧹 드래프트 강제 정리됨", 
                        description=f"관리자에 의해 드래프트가 정리되었어.",
                        color=INFO_COLOR
                    ))
        except Exception as e:
            logger.warning(f"Failed to send cleanup notification: {e}")
        
        await self.send_success(ctx_or_interaction, f"채널 {target_channel_id}의 드래프트를 정리했어.")
        logger.info(f"Force cleanup completed for channel {target_channel_id} by user {user_id}")

    @command_handler()
    async def _handle_audit_query(self, ctx_or_interaction: CommandContext, limit: int = 10) -> None:
        """Handle audit log query"""
        if not self._has_admin_permission(ctx_or_interaction):
            await self.send_error(ctx_or_interaction, "이 명령어는 메시지 관리 권한이 있는 사용자만 사용할 수 있어.")
            return
        
        # Validate limit
        if limit < 1 or limit > 50:
            await self.send_error(ctx_or_interaction, "조회 개수는 1-50 사이여야 해.")
            return
        
        # Get recent logs
        recent_logs = self.audit_logs[-limit:] if self.audit_logs else []
        
        if not recent_logs:
            await self.send_error(ctx_or_interaction, "감사 로그가 없어.")
            return
        
        # Format logs
        embed = discord.Embed(
            title="🔍 드래프트 감사 로그",
            description=f"최근 {len(recent_logs)}개 항목",
            color=INFO_COLOR
        )
        
        for log in reversed(recent_logs):  # Most recent first
            timestamp = int(log["timestamp"])
            action = log["action"]
            user_id = log["user_id"]
            data = log["data"]
            
            user_mention = f"<@{user_id}>" if user_id else "시스템"
            data_items = []
            for k, v in data.items():
                if k == "channel_id":
                    data_items.append(f"채널:<#{v}>")
                else:
                    data_items.append(f"{k}:{v}")
            data_str = ", ".join(data_items) if data_items else "없음"
            
            embed.add_field(
                name=f"{action} - <t:{timestamp}:R>",
                value=f"사용자: {user_mention}\n데이터: {data_str}",
                inline=False
            )
        
        await self.send_response(ctx_or_interaction, embed=embed, ephemeral=True)

    async def _start_servant_selection(self, draft: DraftSession = None) -> None:
        """Start servant selection phase using ephemeral interfaces"""
        # Use provided draft or find the current one
        if draft:
            current_draft = draft
        else:
            # Find the current draft (fallback for legacy calls)
            current_draft = None
            for channel_id, d in self.active_drafts.items():
                if d.phase == DraftPhase.SERVANT_SELECTION:
                    current_draft = d
                    break
        
        if not current_draft:
            logger.warning(f"Could not find current draft")
            return
        
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(current_draft)
        if not channel:
            logger.warning(f"Could not get draft channel for draft in {current_draft.channel_id}")
            return
        
        # Remove banned servants from available list
        current_draft.available_servants = current_draft.available_servants - current_draft.banned_servants
        
        # Initialize selection progress tracking
        for user_id in current_draft.players.keys():
            current_draft.selection_progress[user_id] = False
        
        # Send static button message (never recreated)
        button_embed = discord.Embed(
            title="⚔️ 서번트 선택",
            description="**👇 아래 버튼을 눌러서 자신의 서번트를 선택해!**\n"
                       "• 개인 선택창이 열려 (나만 볼 수 있음)\n"
                       "• 선택 내용은 모든 플레이어가 완료된 후에 공개될거야\n"
                       f"⏰ **제한 시간: {current_draft.selection_time_limit // 60}분 {current_draft.selection_time_limit % 60}초**",
            color=INFO_COLOR
        )
        
        # Show banned servants summary in button message
        if current_draft.banned_servants:
            banned_list = ", ".join(sorted(current_draft.banned_servants))
            button_embed.add_field(name="🚫 밴된 서번트", value=banned_list, inline=False)
        
        # Create static button view (this will never be recreated)
        view = EphemeralSelectionView(current_draft, self)
        self._register_view(current_draft.channel_id, view)
        try:
            button_message = await self._safe_api_call(
                lambda: channel.send(embed=button_embed, view=view), 
                bucket=f"selection_buttons_{current_draft.channel_id}"
            )
            current_draft.selection_buttons_message_id = button_message.id
            logger.info(f"Created static button message {button_message.id}")
        except Exception as e:
            logger.error(f"Failed to send selection button message: {e}")
            raise
        
        # Send separate progress message (this will be updated)
        progress_embed = discord.Embed(
            title="📊 선택 진행 상황",
            description="각 플레이어의 선택 진행 상황을 실시간으로 표시해.",
            color=INFO_COLOR
        )
        
        await self._update_selection_progress_embed(current_draft, progress_embed)
        
        try:
            progress_message = await self._safe_api_call(
                lambda: channel.send(embed=progress_embed), 
                bucket=f"selection_progress_{current_draft.channel_id}"
            )
            current_draft.selection_progress_message_id = progress_message.id
            logger.info(f"Created progress message {progress_message.id}")
        except Exception as e:
            logger.error(f"Failed to send selection progress message: {e}")
            raise
        
        # Initialize servant selection timer
        current_draft.selection_start_time = time.monotonic()
        
        # Start background timer task
        task = asyncio.create_task(self._servant_selection_timer(current_draft))
        current_draft.running_tasks.add(task)
        task.add_done_callback(current_draft.running_tasks.discard)
        
        # Auto-complete fake players' selections immediately in test mode
        if current_draft.is_test_mode:
            await self._auto_complete_test_selections(current_draft)
            await self._update_selection_progress_message(current_draft)

    async def _update_selection_progress_embed(self, draft: DraftSession, embed: discord.Embed) -> None:
        """Update selection progress in the embed"""
        progress_text = ""
        completed_count = 0
        
        if draft.phase == DraftPhase.SERVANT_RESELECTION:
            # During reselection, only show progress for players who need to reselect
            reselect_users = set()
            for servant, user_ids in draft.conflicted_servants.items():
                reselect_users.update(user_ids)
            
            for user_id in reselect_users:
                player = draft.players[user_id]
                status = "✅ 완료" if draft.selection_progress.get(user_id, False) else "⏳ 진행 중"
                progress_text += f"{player.username}: {status}\n"
                if draft.selection_progress.get(user_id, False):
                    completed_count += 1
            
            total_players = len(reselect_users)
            embed.add_field(
                name=f"재선택 진행 상황 ({completed_count}/{total_players})",
                value=progress_text.strip(),
                inline=False
            )
        else:
            # Regular servant selection - show all players
            for user_id, player in draft.players.items():
                status = "✅ 완료" if draft.selection_progress.get(user_id, False) else "⏳ 진행 중"
                progress_text += f"{player.username}: {status}\n"
                if draft.selection_progress.get(user_id, False):
                    completed_count += 1
            
            total_players = len(draft.players)
            embed.add_field(
                name=f"진행 상황 ({completed_count}/{total_players})",
                value=progress_text.strip(),
                inline=False
            )

    async def _update_selection_progress_message(self, draft: DraftSession) -> None:
        """Update the separate progress message (no view recreation)"""
        if not draft.selection_progress_message_id:
            return
            
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            return
            
        try:
            # Create hash of current progress to detect changes
            progress_hash = hash(frozenset(draft.selection_progress.items()))
            
            # Skip update if progress hasn't changed
            if draft.last_progress_update_hash == str(progress_hash):
                logger.debug("Progress unchanged, skipping message update")
                return
                
            draft.last_progress_update_hash = str(progress_hash)
            logger.info(f"Updating progress message {draft.selection_progress_message_id}, hash: {progress_hash}")
            
            message = await channel.fetch_message(draft.selection_progress_message_id)
            
            # Create progress-only embed
            embed = discord.Embed(
                title="📊 선택 진행 상황",
                description="각 플레이어의 선택 진행 상황을 실시간으로 표시해.",
                color=INFO_COLOR
            )
            
            await self._update_selection_progress_embed(draft, embed)
            
            # Only update the embed, never touch the view (no view for progress message)
            await message.edit(embed=embed)
            logger.debug(f"Successfully updated progress message")
            
        except discord.NotFound:
            logger.warning("Selection progress message not found")

    async def _auto_complete_test_selections(self, draft: DraftSession) -> None:
        """Auto-complete servant selections for test mode fake players"""
        
        # Get available servants (exclude banned and already selected)
        taken_servants = {p.selected_servant for p in draft.players.values() if p.selected_servant}
        available_servants = list(draft.available_servants - draft.banned_servants - taken_servants)
        
        # Auto-select for players who haven't selected yet
        for user_id, player in draft.players.items():
            if not player.selected_servant and user_id != draft.real_user_id:  # Fake player
                if available_servants:
                    servant = random.choice(available_servants)
                    player.selected_servant = servant
                    draft.selection_progress[user_id] = True
                    

                    
                    available_servants.remove(servant)
                    logger.info(f"Auto-selected {servant} for fake player {player.username}")

    async def _reveal_servant_selections(self, draft: DraftSession = None) -> None:
        """Reveal servant selections and handle conflicts. After confirmations, offer manual vs AI team composition."""
        # Use provided draft or find the current one
        if draft:
            current_draft = draft
            current_channel_id = draft.channel_id
        else:
            # Find the current draft (fallback for legacy calls)
            current_draft = None
            current_channel_id = None
            for channel_id, d in self.active_drafts.items():
                if d.phase == DraftPhase.SERVANT_SELECTION:
                    current_draft = d
                    current_channel_id = channel_id
                    break
        
        if not current_draft:
            return
        
        # Find conflicts
        servant_users = {}
        for user_id, player in current_draft.players.items():
            servant = player.selected_servant
            if servant not in servant_users:
                servant_users[servant] = []
            servant_users[servant].append(user_id)
        
        conflicts = {servant: users for servant, users in servant_users.items() if len(users) > 1}
        
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(current_draft)
        if not channel:
            logger.warning(f"Could not get draft channel for revealing servant selections")
            return
        
        if conflicts:
            # Handle conflicts with dice rolls
            embed = discord.Embed(
                title="🎲 서번트 선택 결과 - 중복이 있어.",
                description="중복 선택된 서번트가 있네. 주사위로 결정하자.",
                color=ERROR_COLOR
            )
            
            for servant, user_ids in conflicts.items():
                # Keep original list for later use
                original_conflicted_users = user_ids.copy()
                
                # Roll dice for each conflicted user with tie-breaking
                rolls = {}
                max_attempts = 5  # Prevent infinite loops
                attempt = 0
                
                while attempt < max_attempts:
                    # Roll dice for all conflicted users
                    for user_id in user_ids:
                        rolls[user_id] = random.randint(1, 20)
                    
                    # Check for ties at the highest roll
                    max_roll = max(rolls.values())
                    winners = [uid for uid, roll in rolls.items() if roll == max_roll]
                    
                    if len(winners) == 1:
                        # Clear winner found
                        winner_id = winners[0]
                        break
                    else:
                        # Tie detected, re-roll only the tied players
                        user_ids = winners  # Only re-roll the tied players
                        attempt += 1
                        logger.info(f"Dice tie for {servant}, re-rolling attempt {attempt}")
                
                # If still tied after max attempts, use deterministic fallback
                if len(winners) > 1:
                    winner_id = min(winners)  # Use lowest user ID as tiebreaker
                    logger.warning(f"Max re-roll attempts reached for {servant}, using user ID tiebreaker")
                
                # Set winner and reset losers - use original list to get ALL losers
                current_draft.confirmed_servants[winner_id] = servant
                original_losers = [uid for uid in original_conflicted_users if uid != winner_id]
                current_draft.conflicted_servants[servant] = original_losers
                
                # Reset only the losers (not the winner)
                for user_id in original_losers:
                    current_draft.players[user_id].selected_servant = None
                    current_draft.selection_progress[user_id] = False  # Allow reselection
                
                # Add to embed with tie information
                roll_text = "\n".join([
                    f"{current_draft.players[uid].username}: {rolls[uid]} {'✅' if uid == winner_id else '❌'}"
                    for uid in original_conflicted_users  # Show all original players
                ])
                if attempt > 0:
                    roll_text += f"\n(재굴림 {attempt}회)"
                embed.add_field(name=f"{servant} 중복", value=roll_text, inline=True)
            
            # Confirm non-conflicted servants
            for servant, user_ids in servant_users.items():
                if len(user_ids) == 1:
                    current_draft.confirmed_servants[user_ids[0]] = servant
            
            await self._safe_api_call(
                lambda: channel.send(embed=embed),
                bucket=f"reveal_{current_draft.channel_id}"
            )
            
            # If there are losers, start reselection
            if any(current_draft.conflicted_servants.values()):
                current_draft.phase = DraftPhase.SERVANT_RESELECTION
                await self._start_servant_reselection(current_draft, current_channel_id)
            else:
                # No conflicts left; offer composition options instead of jumping straight to manual selection
                try:
                    await self._offer_team_composition_options(current_draft)
                except Exception as e:
                    logger.warning(f"Failed to present composition options, fallback to manual selection: {e}")
                    await self._start_team_selection(current_draft, current_channel_id)
        else:
            # No conflicts, confirm all
            for user_id, player in current_draft.players.items():
                current_draft.confirmed_servants[user_id] = player.selected_servant
            
            embed = discord.Embed(
                title="✅ 서번트 선택 완료",
                description="모든 플레이어의 서번트 선택이 완료됐어. 이제 팀 구성 방법을 선택해:",
                color=SUCCESS_COLOR
            )
            
            # Show all selections grouped by category
            for category, characters in current_draft.servant_categories.items():
                selected_in_category = []
                for player in current_draft.players.values():
                    if player.selected_servant in characters:
                        selected_in_category.append(f"{player.selected_servant}: {player.username}")
                
                if selected_in_category:
                    embed.add_field(
                        name=f"{category} 클래스",
                        value="\n".join(selected_in_category),
                        inline=True
                    )
            
            # Send selection completion and offer team composition options
            completion_channel = self._get_draft_channel(current_draft)
            if completion_channel:
                await self._safe_api_call(
                    lambda: completion_channel.send(embed=embed),
                    bucket=f"reveal_{current_draft.channel_id}"
                )
                # Offer manual vs automatic team composition choice
                try:
                    await self._offer_team_composition_options(current_draft)
                except Exception as e:
                    logger.warning(f"Failed to present composition options, falling back to manual: {e}")
                    await self._start_team_selection(current_draft, current_channel_id)
            else:
                await self._start_team_selection(current_draft, current_channel_id)

    async def _start_servant_reselection(self, draft: DraftSession, channel_id: int) -> None:
        """Start servant reselection for conflict losers"""
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            logger.warning(f"Could not get draft channel for servant reselection")
            return
        
        # Increment reselection round and check for infinite loops
        draft.reselection_round += 1
        if draft.reselection_round > 5:  # Safety limit
            logger.error(f"Too many reselection rounds ({draft.reselection_round}), forcing completion")
            # Force proceed to team selection to prevent infinite loops
            await self._start_team_selection(draft, channel_id)
            return
        
        # Get users who need to reselect
        reselect_users = []
        for servant, user_ids in draft.conflicted_servants.items():
            reselect_users.extend(user_ids)
        
        # Auto-ban cloaking servants for reselection if no detection servant is confirmed
        # This reduces second-mover advantage by removing hidden-info picks when counters are absent
        auto_bans_for_reselection = []
        try:
            confirmed_now = set(draft.confirmed_servants.values())
            has_detection = any(s in draft.detection_servants for s in confirmed_now)
            if not has_detection:
                auto_bans_for_reselection = [
                    s for s in draft.cloaking_servants if s not in draft.banned_servants
                ]
                if auto_bans_for_reselection:
                    draft.banned_servants.update(auto_bans_for_reselection)
                    logger.info(
                        f"Reselection auto-bans applied (no detection confirmed): {auto_bans_for_reselection}"
                    )
                    # Announce publicly for clarity
                    announcement = discord.Embed(
                        title="🚫 재선택 자동 금지 적용",
                        description=(
                            "탐지 능력을 가진 서번트가 존재하지 않아, \n"
                            "은신 서번트들은 재선택 단계에서 제외되었어:"
                        ),
                        color=INFO_COLOR
                    )
                    announcement.add_field(
                        name="은신 서번트 제외",
                        value=", ".join(auto_bans_for_reselection),
                        inline=False
                    )
                    await self._safe_api_call(
                        lambda: channel.send(embed=announcement),
                        bucket=f"reselection_autobans_{channel_id}"
                    )
        except Exception as e:
            logger.warning(f"Failed to compute reselection auto-bans: {e}")
        
        # Remove taken servants from available list
        taken_servants = set(draft.confirmed_servants.values())
        draft.available_servants = draft.available_servants - taken_servants - draft.banned_servants
        
        embed = discord.Embed(
            title="⚔️ 서번트 선택 결과 - 중복이 있어",
            description="중복 선택된 서번트가 있네. 주사위로 결정하자.\n"
                       "일부 서번트는 확정되었고, 중복된 플레이어들은 재선택해야 해.\n"
                       f"⏰ **재선택 제한 시간: {draft.reselection_time_limit // 60}분 {draft.reselection_time_limit % 60}초**",
            color=INFO_COLOR
        )
        
        # Show confirmed servants (locked in) - hide player names during reselection
        if draft.confirmed_servants:
            confirmed_chars_only = sorted(set(draft.confirmed_servants.values()))
            embed.add_field(
                name="✅ 확정된 서번트 (수정 불가)",
                value="\n".join([f"🔒 {s}" for s in confirmed_chars_only]),
                inline=False
            )
        
        # Announce any auto-bans applied for reselection
        if auto_bans_for_reselection:
            embed.add_field(
                name="🚫 재선택 자동 금지 (은신)",
                value=", ".join(auto_bans_for_reselection),
                inline=False
            )
        
        # Show reselection targets  
        reselect_names = [draft.players[uid].username for uid in reselect_users]
        embed.add_field(name="🔄 재선택 대상", value="\n".join(reselect_names), inline=False)
        
        # Show available characters in first category (exclude confirmed + banned)
        available_saber = [
            char for char in draft.servant_categories["세이버"] 
            if char not in taken_servants and char not in draft.banned_servants
        ]
        if available_saber:
            embed.add_field(
                name="세이버 사용 가능",
                value="\n".join([f"✅ {char}" for char in available_saber]),
                inline=True
            )
        
        embed.add_field(
            name="📋 재선택 방법",
            value="각자의 개인 선택 버튼을 사용해서 재선택해줘.\n"
                  "🔒 확정된 서번트와 ❌ 금지된 서번트는 선택할 수 없어.",
            inline=False
        )
        
        # During reselection, create new button interface for conflicted players only
        view = EphemeralSelectionView(draft, self)
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"reselection_{channel_id}"
        )
        
        # Send separate progress message for reselection (similar to servant selection)
        progress_embed = discord.Embed(
            title="📊 재선택 진행 상황",
            description="재선택 대상 플레이어들의 진행 상황을 실시간으로 표시해.",
            color=INFO_COLOR
        )
        
        await self._update_selection_progress_embed(draft, progress_embed)
        
        try:
            progress_message = await self._safe_api_call(
                lambda: channel.send(embed=progress_embed), 
                bucket=f"reselection_progress_{channel_id}"
            )
            draft.selection_progress_message_id = progress_message.id  # Reuse same field
            logger.info(f"Created reselection progress message {progress_message.id}")
        except Exception as e:
            logger.error(f"Failed to send reselection progress message: {e}")
        
        # Initialize servant reselection timer
        draft.reselection_start_time = time.monotonic()
        
        # Start background timer task
        task = asyncio.create_task(self._servant_reselection_timer(draft))
        draft.running_tasks.add(task)
        task.add_done_callback(draft.running_tasks.discard)
        
        # Auto-complete reselection for fake players in test mode
        if draft.is_test_mode:
            await self._auto_complete_reselection(draft)
            await self._update_selection_progress_message(draft)

    async def _auto_complete_reselection(self, draft: DraftSession) -> None:
        """Auto-complete servant reselection for fake players in test mode"""
        
        # Get available servants (exclude confirmed and banned)
        confirmed_servants = set(draft.confirmed_servants.values())
        available_servants = list(draft.available_servants - confirmed_servants - draft.banned_servants)
        
        # Auto-select for fake players who need to reselect
        completed_fake_players = set()
        for servant, conflict_user_ids in draft.conflicted_servants.items():
            for user_id in conflict_user_ids:
                if user_id != draft.real_user_id and available_servants:  # Fake player needs reselection
                    new_servant = random.choice(available_servants)
                    draft.players[user_id].selected_servant = new_servant
                    available_servants.remove(new_servant)
                    completed_fake_players.add(user_id)
                    logger.info(f"Auto-reselected {new_servant} for fake player {draft.players[user_id].username}")
        
        # Remove only completed fake players from conflicts, preserve real user's conflict
        for servant in list(draft.conflicted_servants.keys()):
            # Remove fake players who completed reselection from this conflict
            draft.conflicted_servants[servant] = [
                user_id for user_id in draft.conflicted_servants[servant] 
                if user_id not in completed_fake_players
            ]
            # Remove empty conflict entries
            if not draft.conflicted_servants[servant]:
                del draft.conflicted_servants[servant]

    async def _check_reselection_completion(self, draft: DraftSession) -> None:
        """Check if reselection phase is complete and proceed if so"""
        # Get all players who need to reselect (from conflicts)
        conflicted_players = set()
        for user_ids in draft.conflicted_servants.values():
            conflicted_players.update(user_ids)
        
        # Check if all conflicted players have made new selections
        all_reselected = True
        for user_id in conflicted_players:
            player = draft.players[user_id]
            if not player.selected_servant:
                all_reselected = False
                break
        
        # If all reselected, reveal selections again (may find new conflicts)
        if all_reselected:
            await self._reveal_servant_selections(draft)

    async def _start_team_selection(self, draft: DraftSession, channel_id: int) -> None:
        """Start team selection phase"""
        draft.phase = DraftPhase.TEAM_SELECTION
        
        # Roll dice to determine first pick
        captain1, captain2 = draft.captains
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20)
        
        # Handle ties with re-rolls
        while roll1 == roll2:
            roll1 = random.randint(1, 20)
            roll2 = random.randint(1, 20)
        
        if roll1 > roll2:
            draft.first_pick_captain = captain1
        else:
            draft.first_pick_captain = captain2
        
        # Initialize team picking
        draft.team_selection_round = 1
        draft.current_picking_captain = draft.first_pick_captain
        draft.picks_this_round = {captain1: 0, captain2: 0}
        # Initialize team selection progress tracking
        draft.team_selection_progress = {captain1: {}, captain2: {}}
        
        # Assign captains to teams
        draft.players[captain1].team = 1
        draft.players[captain2].team = 2
        
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            logger.warning(f"Could not get draft channel for team selection start")
            return
        
        embed = discord.Embed(
            title="👥 팀원 선택 시작",
            description="팀장들이 순서대로 팀원을 선택해.",
            color=INFO_COLOR
        )
        
        embed.add_field(
            name="주사위 결과",
            value=f"{draft.players[captain1].username}: {roll1}\n"
                  f"{draft.players[captain2].username}: {roll2}",
            inline=True
        )
        
        first_pick_name = draft.players[draft.first_pick_captain].username
        embed.add_field(name="선픽", value=first_pick_name, inline=True)
        
        await self._safe_api_call(
            lambda: channel.send(embed=embed),
            bucket=f"team_selection_start_{channel_id}"
        )
        
        # Announce hybrid mode - non-captains can leave thread
        await self._announce_team_selection_hybrid_mode(draft)
        
        await self._continue_team_selection_for_draft(draft)

    async def _continue_team_selection_for_draft(self, draft: DraftSession) -> None:
        """Continue team selection process for a specific draft"""
        # Check if team selection is complete
        total_players = draft.team_size * 2
        assigned_players = sum(1 for p in draft.players.values() if p.team is not None)
        if assigned_players == total_players:
            # Skip final swap phase and proceed directly to completion
            await self._complete_draft(draft)
            return
        
        # Get current round pattern
        round_info = self.team_selection_patterns[draft.team_size][draft.team_selection_round - 1]
        current_captain = draft.current_picking_captain
        
        # Check if current captain finished their picks for this round
        picks_made = draft.picks_this_round.get(current_captain, 0)
        is_first_pick = current_captain == draft.first_pick_captain
        max_picks = round_info["first_pick"] if is_first_pick else round_info["second_pick"]
        
        if picks_made >= max_picks:
            # Switch to other captain or next round
            other_captain = [c for c in draft.captains if c != current_captain][0]
            other_picks = draft.picks_this_round.get(other_captain, 0)
            other_max = round_info["second_pick"] if is_first_pick else round_info["first_pick"]
            
            if other_picks < other_max:
                # Switch to other captain
                draft.current_picking_captain = other_captain
            else:
                # Move to next round
                draft.team_selection_round += 1
                draft.picks_this_round = {draft.captains[0]: 0, draft.captains[1]: 0}
                # Reset progress tracking for new round (don't clear history, just don't mark new round as completed yet)
                draft.current_picking_captain = draft.first_pick_captain
        
        # Show current picking status and available players
        await self._show_team_selection_status_for_draft(draft)

    async def _show_team_selection_status_for_draft(self, draft: DraftSession) -> None:
        """Show current team selection status for a specific draft"""
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            logger.warning(f"Could not get draft channel for team selection status")
            return
        
        current_captain = draft.current_picking_captain
        round_info = self.team_selection_patterns[draft.team_size][draft.team_selection_round - 1]
        
        embed = discord.Embed(
            title=f"👥 팀 선택 - 라운드 {draft.team_selection_round}",
            description=f"현재 {draft.players[current_captain].username}의 차례야.",
            color=INFO_COLOR
        )
        
        # Show available players (exclude those already assigned or in pending selections)
        all_pending_selections = set()
        for pending_list in draft.pending_team_selections.values():
            all_pending_selections.update(pending_list)
        
        available_players = [
            p for p in draft.players.values() 
            if p.team is None and not p.is_captain and p.user_id not in all_pending_selections
        ]
        
        if available_players:
            available_list = "\n".join([
                f"{i+1}. {draft.confirmed_servants[p.user_id]} ({p.username})"
                for i, p in enumerate(available_players)
            ])
            embed.add_field(name="선택 가능한 플레이어", value=available_list, inline=False)
        
        # Show current teams
        team1_players = [p for p in draft.players.values() if p.team == 1]
        team2_players = [p for p in draft.players.values() if p.team == 2]
        
        team1_text = "\n".join([f"{draft.confirmed_servants[p.user_id]} ({p.username})" for p in team1_players])
        team2_text = "\n".join([f"{draft.confirmed_servants[p.user_id]} ({p.username})" for p in team2_players])
        
        embed.add_field(name="팀 1", value=team1_text or "없음", inline=True)
        embed.add_field(name="팀 2", value=team2_text or "없음", inline=True)
        
        # Show pending selections if any
        pending_selections = draft.pending_team_selections.get(current_captain, [])
        if pending_selections:
            pending_names = [draft.players[pid].username for pid in pending_selections]
            captain_team = draft.players[current_captain].team
            embed.add_field(
                name=f"팀 {captain_team} 선택 대기 중",
                value="\n".join([f"• {name}" for name in pending_names]),
                inline=False
            )
        
        # Create selection view with confirmation button
        view = TeamSelectionView(draft, self, available_players)
        self._register_view(draft.channel_id, view)
        
        # Send to thread with interactive view
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"team_selection_status_{draft.channel_id}"
        )
        
        # Also send status update to main channel (without view)
        main_channel = self.bot.get_channel(draft.channel_id) if self.bot else None
        if main_channel and draft.thread_id:  # Only if in hybrid mode
            try:
                main_embed = discord.Embed(
                    title=f"📊 팀 선택 진행 상황 - 라운드 {draft.team_selection_round}",
                    description=f"현재 **{draft.players[current_captain].username}**의 차례",
                    color=INFO_COLOR
                )
                
                # Show current teams more concisely for main channel
                team1_players = [p for p in draft.players.values() if p.team == 1]
                team2_players = [p for p in draft.players.values() if p.team == 2]
                
                team1_text = "\n".join([f"• {draft.confirmed_servants[p.user_id]} ({p.username})" for p in team1_players])
                team2_text = "\n".join([f"• {draft.confirmed_servants[p.user_id]} ({p.username})" for p in team2_players])
                
                main_embed.add_field(name="팀 1", value=team1_text or "없음", inline=True)
                main_embed.add_field(name="팀 2", value=team2_text or "없음", inline=True)
                
                # Show pending selections if any
                pending_selections = draft.pending_team_selections.get(current_captain, [])
                if pending_selections:
                    pending_names = [draft.players[pid].username for pid in pending_selections]
                    captain_team = draft.players[current_captain].team
                    main_embed.add_field(
                        name=f"팀 {captain_team} 선택 대기 중",
                        value="\n".join([f"• {name}" for name in pending_names]),
                        inline=False
                    )
                
                await self._safe_api_call(
                    lambda: main_channel.send(embed=main_embed),
                    bucket=f"team_selection_main_status_{draft.channel_id}"
                )
            except Exception as e:
                logger.warning(f"Failed to send team selection status to main channel: {e}")

    async def _refresh_team_selection_interface(self, draft: DraftSession) -> None:
        """Refresh the team selection interface to show pending selections"""
        # For now, just show an updated status - in a full implementation you might want to 
        # edit the existing message instead of sending a new one
        await self._show_team_selection_status_for_draft(draft)

    @command_handler()
    async def _handle_draft_cancel(self, ctx_or_interaction: CommandContext) -> None:
        """Handle draft cancellation"""
        channel_id = self.get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_drafts:
            await self.send_error(ctx_or_interaction, "진행 중인 드래프트가 없어.")
            return
        
        # Get draft for cleanup
        draft = self.active_drafts[channel_id]
        
        # Audit log
        self._audit_log("draft_cancel", self.get_user_id(ctx_or_interaction), {
            "channel_id": channel_id,
            "draft_phase": draft.phase.value
        })
        
        # Stop all active views to prevent memory leaks
        await self._cleanup_views(channel_id)
        
        # Clean up all message IDs to prevent memory leaks
        await self._cleanup_all_message_ids(draft)
        
        # Remove from tracking
        del self.active_drafts[channel_id]
        if channel_id in self.draft_start_times:
            del self.draft_start_times[channel_id]
        
        logger.info(f"Draft cancelled in channel {channel_id} with full cleanup")
        await self.send_success(ctx_or_interaction, "드래프트를 취소했어.")

    def _sanitize_username(self, username: str) -> str:
        """Sanitize username to prevent Discord embed issues"""
        # Remove or escape characters that could break Discord embeds
        sanitized = username.replace('`', '\\`')  # Escape backticks
        sanitized = sanitized.replace('*', '\\*')  # Escape asterisks
        sanitized = sanitized.replace('_', '\\_')  # Escape underscores
        sanitized = sanitized.replace('~', '\\~')  # Escape tildes
        sanitized = sanitized.replace('|', '\\|')  # Escape pipes
        sanitized = sanitized.replace('[', '\\[')  # Escape brackets
        sanitized = sanitized.replace(']', '\\]')  # Escape brackets
        sanitized = sanitized.replace('(', '\\(')  # Escape parentheses
        sanitized = sanitized.replace(')', '\\)')  # Escape parentheses
        
        # Limit length to prevent extremely long names
        if len(sanitized) > 32:
            sanitized = sanitized[:29] + "..."
            
        return sanitized

    async def _start_servant_ban_phase(self, draft: DraftSession) -> None:
        """Start servant ban phase with automated system bans followed by captain bans"""
        logger.info("Starting servant ban phase")
        
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            logger.warning("Could not get draft channel for servant ban phase")
            return
        
        logger.info("Got draft channel, proceeding with system bans")
        
        # Step 1: Perform automated system bans
        await self._perform_system_bans(draft, channel)
        logger.info("Completed system bans")
        
        # Step 2: Determine captain ban order with dice roll
        await self._determine_captain_ban_order(draft, channel)
        logger.info("Completed captain ban order determination")
        
        # Step 3: Start captain ban phase
        await self._start_captain_bans(draft, channel)
        logger.info("Completed starting captain bans")

    async def _perform_system_bans(self, draft: DraftSession, channel) -> None:
        """Perform automated system bans before captain bans"""
        logger.info("Starting system bans")
        
        system_bans = []
        
        # Get available servants for each tier (exclude already banned)
        available_s_tier = [s for s in draft.servant_tiers["S"] if s in draft.available_servants]
        available_a_tier = [s for s in draft.servant_tiers["A"] if s in draft.available_servants]
        available_b_tier = [s for s in draft.servant_tiers["B"] if s in draft.available_servants]
        
        logger.info(f"Available tiers - S: {len(available_s_tier)}, A: {len(available_a_tier)}, B: {len(available_b_tier)}")
        
        # 1 random from S tier (if possible)
        s_bans = []
        for _ in range(min(1, len(available_s_tier))):
            s_ban = random.choice(available_s_tier)
            s_bans.append(s_ban)
            system_bans.append(s_ban)
            draft.available_servants.discard(s_ban)
            available_s_tier.remove(s_ban)
            available_a_tier = [s for s in available_a_tier if s != s_ban]  # Remove from other tiers if duplicate
            available_b_tier = [s for s in available_b_tier if s != s_ban]
        
        # 1 random from A tier
        if available_a_tier:
            a_ban = random.choice(available_a_tier)
            system_bans.append(a_ban)
            draft.available_servants.discard(a_ban)
            available_b_tier = [s for s in available_b_tier if s != a_ban]  # Remove from B tier if duplicate
        
        # 1 random from B tier
        if available_b_tier:
            b_ban = random.choice(available_b_tier)
            system_bans.append(b_ban)
            draft.available_servants.discard(b_ban)
        
        # Store system bans
        draft.system_bans = system_bans
        draft.banned_servants.update(system_bans)
        
        logger.info(f"Selected system bans: {system_bans}")
        
        # Announce system bans
        embed = discord.Embed(
            title="문 셀 오토마톤",
            description="문 셀이 자동으로 서번트를 밴했어.",
            color=INFO_COLOR
        )
        
        if system_bans:
            ban_details = []
            s_bans = [b for b in system_bans if b in draft.servant_tiers["S"]]
            a_bans = [b for b in system_bans if b in draft.servant_tiers["A"]]
            b_bans = [b for b in system_bans if b in draft.servant_tiers["B"]]
            
            if s_bans:
                ban_details.append(f"**갑**: {', '.join(s_bans)}")
            if a_bans:
                ban_details.append(f"**을**: {', '.join(a_bans)}")
            if b_bans:
                ban_details.append(f"**병**: {', '.join(b_bans)}")
            
            embed.add_field(name="추방된 서번트", value="\n".join(ban_details), inline=False)
            embed.add_field(name="문 셀 밴", value=f"{len(system_bans)}개", inline=True)
        
        logger.info("Sending system ban announcement")
        await self._safe_api_call(
            lambda: channel.send(embed=embed),
            bucket=f"system_bans_{draft.channel_id}"
        )
        logger.info("System bans completed successfully")

    async def _determine_captain_ban_order(self, draft: DraftSession, channel) -> None:
        """Determine captain ban order using dice roll"""
        
        captain1, captain2 = draft.captains
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20)
        
        # Handle ties with re-rolls
        while roll1 == roll2:
            roll1 = random.randint(1, 20)
            roll2 = random.randint(1, 20)
        
        # Determine order (higher roll goes first)
        if roll1 > roll2:
            draft.captain_ban_order = [captain1, captain2]
        else:
            draft.captain_ban_order = [captain2, captain1]
        
        draft.current_banning_captain = draft.captain_ban_order[0]
        
        # Announce dice roll results
        embed = discord.Embed(
            title="🎲 팀장 밴 순서 결정",
            description="주사위로 어느 팀장이 먼저 밴할지 정했어.",
            color=INFO_COLOR
        )
        
        embed.add_field(
            name="주사위 결과",
            value=f"{draft.players[captain1].username}: {roll1}\n"
                  f"{draft.players[captain2].username}: {roll2}",
            inline=True
        )
        
        first_captain_name = draft.players[draft.captain_ban_order[0]].username
        embed.add_field(name="먼저 밴하는 팀장", value=first_captain_name, inline=True)
        embed.add_field(name="밴 횟수", value="팀장마다 1명씩", inline=True)
        
        await self._safe_api_call(
            lambda: channel.send(embed=embed),
            bucket=f"ban_order_{draft.channel_id}"
        )

    async def _start_captain_bans(self, draft: DraftSession, channel) -> None:
        """Start the captain ban phase with sequential ordering"""
        # Initialize ban progress tracking
        for captain_id in draft.captains:
            draft.captain_ban_progress[captain_id] = False
        
        # Send public progress embed
        embed = discord.Embed(
            title="🚫 팀장 밴 단계",
            description="이제 각 팀장이 순서대로 1개씩 밴을 선택해.\n"
                       "밴 내용은 즉시 공개될거야.",
            color=INFO_COLOR
        )
        
        captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
        embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
        
        # Show current system bans
        if draft.system_bans:
            system_ban_text = ", ".join(draft.system_bans)
            embed.add_field(name="문 셀 밴", value=system_ban_text, inline=False)
        
        # Show current banning captain
        current_captain_name = draft.players[draft.current_banning_captain].username
        embed.add_field(name="현재 밴 차례", value=f"**{current_captain_name}**", inline=True)
        
        # Add progress status
        await self._update_captain_ban_progress_embed(draft, embed)
        
        # Send public message and create ephemeral ban buttons
        view = EphemeralCaptainBanView(draft, self)
        message = await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"captain_ban_{draft.channel_id}"
        )
        draft.ban_progress_message_id = message.id

    async def _update_captain_ban_progress_embed(self, draft: DraftSession, embed: discord.Embed) -> None:
        """Update captain ban progress in the embed"""
        progress_text = ""
        for i, captain_id in enumerate(draft.captain_ban_order):
            captain_name = draft.players[captain_id].username
            if captain_id == draft.current_banning_captain:
                status = "🎯 현재 차례"
            elif draft.captain_ban_progress.get(captain_id, False):
                captain_ban = draft.captain_bans.get(captain_id, [])
                ban_text = captain_ban[0] if captain_ban else "완료"
                status = f"✅ 완료 ({ban_text})"
            else:
                status = "⏳ 대기 중"
            progress_text += f"{i+1}. {captain_name}: {status}\n"
        
        # Update progress field
        for i, field in enumerate(embed.fields):
            if field.name == "진행 상황":
                embed.set_field_at(i, name="진행 상황", value=progress_text.strip(), inline=False)
                return
        
        # Add progress field if not exists
        embed.add_field(name="진행 상황", value=progress_text.strip(), inline=False)

    async def _complete_servant_bans(self, draft: DraftSession) -> None:
        """Complete servant ban phase and reveal banned servants"""
        # Collect all banned servants (captain bans are already in banned_servants)
        all_captain_bans = []
        for captain_id, bans in draft.captain_bans.items():
            all_captain_bans.extend(bans)
        
        # Captain bans are already added to banned_servants when confirmed
        # No need to update banned_servants again
        
        embed = discord.Embed(
            title="🚫 서번트 밴 결과",
            description="모든 밴이 끝났어. 다음 서번트들의 선택이 금지되었네.",
            color=ERROR_COLOR
        )
        
        # Show system bans
        if draft.system_bans:
            system_ban_text = ", ".join(draft.system_bans)
            embed.add_field(name="🎲 문 셀 밴", value=system_ban_text, inline=False)
        
        # Show each captain's bans in order
        for i, captain_id in enumerate(draft.captain_ban_order):
            captain_name = draft.players[captain_id].username
            captain_bans = draft.captain_bans.get(captain_id, [])
            ban_text = captain_bans[0] if captain_bans else "없음"
            embed.add_field(name=f"{i+1}. {captain_name}의 밴", value=ban_text, inline=True)
        
        # Show total banned servants before special rule check
        all_bans = draft.system_bans + all_captain_bans
        banned_list = ", ".join(sorted(all_bans))
        embed.add_field(name="총 밴된 서번트", value=banned_list, inline=False)
        
        # Send ban results to appropriate channel (thread if available)
        channel = self._get_draft_channel(draft)
        if channel:
            await self._safe_api_call(
                lambda: channel.send(embed=embed),
                bucket=f"ban_results_{draft.channel_id}"
            )
        
        # Move to servant selection phase
        draft.phase = DraftPhase.SERVANT_SELECTION
        await self._start_servant_selection(draft)

    async def _advance_captain_ban_turn(self, draft: DraftSession) -> None:
        """Advance to next captain's turn or complete bans if all done"""
        # Check if current captain completed their ban
        current_captain = draft.current_banning_captain
        if not draft.captain_ban_progress.get(current_captain, False):
            return  # Current captain hasn't finished yet
        
        # Find next captain in order
        current_index = draft.captain_ban_order.index(current_captain)
        if current_index + 1 < len(draft.captain_ban_order):
            # Move to next captain
            draft.current_banning_captain = draft.captain_ban_order[current_index + 1]
            await self._update_captain_ban_progress_message(draft)
        else:
            # All captains completed - finish ban phase
            await self._complete_servant_bans(draft)

    async def _update_captain_ban_progress_message(self, draft: DraftSession) -> None:
        """Update the public captain ban progress message"""
        if not draft.ban_progress_message_id:
            return
            
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(draft.ban_progress_message_id)
            embed = discord.Embed(
                title="🚫 팀장 밴 단계",
                description="이제 각 팀장이 순서대로 1개씩 밴을 선택해.\n"
                           "밴 내용은 즉시 공개될거야.",
                color=INFO_COLOR
            )
            
            captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
            embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
            
            # Show current system bans
            if draft.system_bans:
                system_ban_text = ", ".join(draft.system_bans)
                embed.add_field(name="문 셀 밴", value=system_ban_text, inline=False)
            
            # Show completed captain bans in order
            completed_bans = []
            for i, captain_id in enumerate(draft.captain_ban_order):
                captain_name = draft.players[captain_id].username
                if draft.captain_ban_progress.get(captain_id, False):
                    captain_bans = draft.captain_bans.get(captain_id, [])
                    ban_text = captain_bans[0] if captain_bans else "없음"
                    completed_bans.append(f"{i+1}. {captain_name}: {ban_text}")
            
            if completed_bans:
                embed.add_field(name="완료된 팀장 밴", value="\n".join(completed_bans), inline=False)
            
            # Show current banning captain
            if draft.current_banning_captain:
                current_captain_name = draft.players[draft.current_banning_captain].username
                embed.add_field(name="현재 밴 차례", value=f"**{current_captain_name}**", inline=True)
            
            await self._update_captain_ban_progress_embed(draft, embed)
            
            # Keep the same view if not all captains are done
            if not all(draft.captain_ban_progress.values()):
                view = EphemeralCaptainBanView(draft, self)
                self._register_view(draft.channel_id, view)
                await message.edit(embed=embed, view=view)
            else:
                await message.edit(embed=embed, view=None)
        except discord.NotFound:
            logger.warning("Captain ban progress message not found")

    async def _complete_draft(self, target_draft: DraftSession = None) -> None:
        """Complete the draft"""
        # Find current draft
        current_draft = target_draft
        current_channel_id = None
        
        if not current_draft:
            # Fallback: search for any draft that needs completion
            for channel_id, draft in self.active_drafts.items():
                if draft.phase == DraftPhase.TEAM_SELECTION:
                    current_draft = draft
                    current_channel_id = channel_id
                    break
        else:
            # Find channel for provided draft
            for channel_id, draft in self.active_drafts.items():
                if draft == current_draft:
                    current_channel_id = channel_id
                    break
        
        if not current_draft or not current_channel_id:
            return
            
        current_draft.phase = DraftPhase.COMPLETED

        # Record prematch features for ML dataset
        try:
            match_id = f"{current_draft.guild_id}:{current_draft.channel_id}:{int(time.time())}"
            current_draft.match_id = match_id
            captains = [uid for uid, p in current_draft.players.items() if p.is_captain]
            team1_players = [p for p in current_draft.players.values() if p.team == 1]
            team2_players = [p for p in current_draft.players.values() if p.team == 2]

            def _build_features(team_players: List[Player]) -> List[PlayerFeature]:
                features: List[PlayerFeature] = []
                for p in team_players:
                    # Try to enrich with roster ratings if available
                    rp = None
                    try:
                        roster = self.roster_store.load(current_draft.guild_id)
                        rp = next((r for r in roster if r.user_id == p.user_id), None)
                    except Exception:
                        rp = None
                    features.append(
                        PlayerFeature(
                            user_id=p.user_id,
                            display_name=p.username,
                            rating=(rp.rating if rp else None),
                            servant=current_draft.confirmed_servants.get(p.user_id),
                            is_captain=p.is_captain,
                            pick_order=None,
                        )
                    )
                return features

            self.match_recorder.write_prematch(
                match_id=match_id,
                guild_id=current_draft.guild_id,
                channel_id=current_draft.channel_id,
                team_size=current_draft.team_size,
                captains=captains,
                team1=_build_features(team1_players),
                team2=_build_features(team2_players),
                bans=sorted(list(current_draft.banned_servants)) if current_draft.banned_servants else [],
                mode_name=("sim_balanced" if current_draft.is_simulation else None),
                sim_session=getattr(current_draft, "simulation_session_id", None),
                author_id=getattr(current_draft, "simulation_author_id", None),
                is_simulation=current_draft.is_simulation,
                sim_author_captain=getattr(current_draft, "simulation_author_id", None),
                sim_note=("expert_balanced" if current_draft.is_simulation else None),
                draft_type=("simulation" if current_draft.is_simulation else "manual"),
                balance_algorithm=(current_draft.auto_balance_result.get("algorithm") if getattr(current_draft, "auto_balance_result", None) else None),
                predicted_balance_score=(current_draft.auto_balance_result.get("balance_score") if getattr(current_draft, "auto_balance_result", None) else None),
                predicted_confidence=(current_draft.auto_balance_result.get("confidence") if getattr(current_draft, "auto_balance_result", None) else None),
                processing_time=(0.0),
                auto_balance_used=(True if getattr(current_draft, "auto_balance_result", None) else False),
            )
            # Auto-update preferred_servants: add any played servant if missing
            try:
                roster = self.roster_store.load(current_draft.guild_id)
                rp_map = {rp.user_id: rp for rp in roster}
                played: List[Tuple[int, str]] = []
                for p in team1_players + team2_players:
                    char = current_draft.confirmed_servants.get(p.user_id)
                    if char:
                        played.append((p.user_id, char))
                updated: List[RosterPlayer] = []
                for uid, char in played:
                    rp = rp_map.get(uid)
                    if not rp:
                        rp = RosterPlayer(user_id=uid, display_name=str(uid))
                        rp_map[uid] = rp
                    prefs = getattr(rp, 'preferred_servants', []) or []
                    if char not in prefs:
                        prefs.append(char)
                        rp.preferred_servants = prefs
                        updated.append(rp)
                if updated:
                    self.roster_store.add_or_update(current_draft.guild_id, list(rp_map.values()))
            except Exception as _e:
                logger.info(f"Preferred-servants auto-update skipped: {_e}")
        except Exception as e:
            logger.warning(f"Failed to record prematch data: {e}")
        
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(current_draft)
        if not channel:
            return
        
        embed = discord.Embed(
            title="🏆 드래프트 완료!",
            description="로스터가 완성됐어!",
            color=SUCCESS_COLOR
        )
        
        # Show final teams
        team1_players = [p for p in current_draft.players.values() if p.team == 1]
        team2_players = [p for p in current_draft.players.values() if p.team == 2]
        
        def format_final_team(players):
            return "\n".join([
                f"**{current_draft.confirmed_servants[p.user_id]}** - {p.username} {'👑' if p.is_captain else ''}"
                for p in players
            ])
        
        embed.add_field(name="팀 1", value=format_final_team(team1_players), inline=True)
        embed.add_field(name="팀 2", value=format_final_team(team2_players), inline=True)
        
        # Send to thread with simulation-finish button when applicable
        view = None
        try:
            if current_draft.is_simulation:
                view = SimulationFinishView(current_draft, self)
                self._register_view(current_draft.channel_id, view)
        except Exception:
            view = None
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"draft_complete_{current_channel_id}"
        )
        
        # Send final roster to main channel as well for maximum visibility
        main_channel = self.bot.get_channel(current_draft.channel_id) if self.bot else None
        if main_channel and current_draft.thread_id:  # Only if in hybrid mode
            try:
                team_format = f"{current_draft.team_size}v{current_draft.team_size}"
                main_embed = discord.Embed(
                    title=f"🏆 {team_format} 드래프트 완료!",
                    description="**최종 로스터가 확정됐어!**\n"
                               "모두들 수고했어! 🎉",
                    color=SUCCESS_COLOR
                )
                
                main_embed.add_field(name="팀 1 최종 로스터", value=format_final_team(team1_players), inline=True)
                main_embed.add_field(name="팀 2 최종 로스터", value=format_final_team(team2_players), inline=True)
                
                # Add draft summary
                main_embed.add_field(
                    name="드래프트 정보",
                    value=f"👥 참가자: {len(current_draft.players)}명\n"
                          f"🎯 형식: {team_format}",
                    inline=False
                )
                
                await self._safe_api_call(
                    lambda: main_channel.send(embed=main_embed),
                    bucket=f"draft_complete_main_{current_draft.channel_id}"
                )
            except Exception as e:
                logger.warning(f"Failed to send final roster to main channel: {e}")
        
        # After roster finalized, present Finish Game button to record outcome (non-simulation)
        try:
            if not current_draft.is_simulation:
                finish_embed = discord.Embed(
                    title="✅ 로스터 확정!",
                    description="경기가 끝났다면 아래 버튼을 눌러 결과를 기록해.",
                    color=SUCCESS_COLOR,
                )
                view_fg = FinishGameView(current_draft, self)
                self._register_view(current_draft.channel_id, view_fg)
                message = await self._safe_api_call(
                    lambda: channel.send(embed=finish_embed, view=view_fg),
                    bucket=f"finish_game_{current_channel_id}"
                )
                try:
                    current_draft.finish_view_message_id = getattr(message, 'id', None)
                except Exception:
                    current_draft.finish_view_message_id = None
        except Exception as e:
            logger.warning(f"Failed to send finish game view: {e}")

        # Do not cleanup yet; wait for outcome recording
        logger.info(f"Draft roster finalized in channel {current_channel_id}; waiting for outcome record")

    async def _check_voting_completion(self, view: 'CaptainVotingView') -> bool:
        """Check if voting should be completed"""
        # Check if all players have voted (normal case)
        if len(view.user_votes) == len(view.draft.players):
            return True
        
        # For test mode: check if the real user has voted for 2 people
        if view.draft.is_test_mode and view.draft.real_user_id:
            real_user_votes = view.user_votes.get(view.draft.real_user_id)
            if real_user_votes and len(real_user_votes) == 2:
                return True
        
        return False



class TeamSelectionView(discord.ui.View):
    """View for team selection with confirmation"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', available_players: List[Player]):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        
        if available_players:
            self.add_item(PlayerDropdown(available_players, draft, bot_commands))
        
        # Add confirmation button if there are pending selections for current captain
        current_captain = draft.current_picking_captain
        if current_captain and draft.pending_team_selections.get(current_captain):
            self.add_item(ConfirmTeamSelectionButton(current_captain))
            
            # Add remove buttons for each pending selection
            pending_selections = draft.pending_team_selections[current_captain]
            for i, player_id in enumerate(pending_selections):
                if i < 4:  # Limit to 4 remove buttons to avoid Discord limits
                    player_name = draft.players[player_id].username
                    self.add_item(RemovePlayerButton(player_id, player_name, i))


class RemovePlayerButton(discord.ui.Button):
    """Button to remove a player from pending selections"""
    
    def __init__(self, player_id: int, player_name: str, index: int):
        super().__init__(
            label=f"❌ {player_name[:15]}",  # Truncate long names
            style=discord.ButtonStyle.secondary,
            custom_id=f"remove_player_{player_id}",
            row=2 + (index // 5)  # Put remove buttons on separate rows
        )
        self.player_id = player_id
        self.player_name = player_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Remove player from pending selections"""
        user_id = interaction.user.id
        view: TeamSelectionView = self.view
        
        # Validate current phase
        if view.draft.phase != DraftPhase.TEAM_SELECTION:
            await interaction.response.send_message(
                "팀 선택 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        current_captain = view.draft.current_picking_captain
        
        # Validate captain permission
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            # In test mode, real user can remove for any captain
            pass
        elif user_id != current_captain:
            await interaction.response.send_message(
                "자신의 선택만 수정할 수 있어.", ephemeral=True
            )
            return
        
        # REMOVED: Redundant check - current_captain was just assigned from current_picking_captain above
        # if view.draft.current_picking_captain != current_captain:
        #     return  # This check is always false since current_captain = view.draft.current_picking_captain
        
        # Check if captain already completed this round
        current_round = view.draft.team_selection_round
        if (current_captain in view.draft.team_selection_progress and 
            current_round in view.draft.team_selection_progress[current_captain] and
            view.draft.team_selection_progress[current_captain][current_round]):
            await interaction.response.send_message(
                "이번 라운드 선택을 이미 완료했어. 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # Remove player from pending selections
        if (current_captain in view.draft.pending_team_selections and 
            self.player_id in view.draft.pending_team_selections[current_captain]):
            
            view.draft.pending_team_selections[current_captain].remove(self.player_id)
            captain_team = view.draft.players[current_captain].team
            remaining_count = len(view.draft.pending_team_selections[current_captain])
            
            # Get max picks for feedback
            round_info = view.bot_commands.team_selection_patterns[view.draft.team_size][view.draft.team_selection_round - 1]
            is_first_pick = current_captain == view.draft.first_pick_captain
            max_picks = round_info["first_pick"] if is_first_pick else round_info["second_pick"]
            
            await interaction.response.send_message(
                f"❌ **{self.player_name}**을(를) 팀 {captain_team} 후보에서 제거했어!\n"
                f"현재 선택: ({remaining_count}/{max_picks})", 
                ephemeral=True
            )
            
            # Refresh interface to update buttons
            await view.bot_commands._refresh_team_selection_interface(view.draft)
        else:
            await interaction.response.send_message(
                f"**{self.player_name}**은(는) 선택 목록에 없어.", ephemeral=True
            )


class PlayerDropdown(discord.ui.Select):
    """Dropdown for selecting players"""
    
    def __init__(self, available_players: List[Player], draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        self.draft = draft
        self.bot_commands = bot_commands
        
        options = [
            discord.SelectOption(
                label=f"{draft.confirmed_servants[player.user_id]}",
                description=f"마스터: {player.username}",
                value=str(player.user_id)
            )
            for player in available_players[:25]  # Discord limit
        ]
        
        super().__init__(
            placeholder="팀원 선택(고른 뒤 선택 확정 버튼을 눌러줘)",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection - add to pending selections instead of immediately assigning"""
        user_id = interaction.user.id
        
        # Validate current phase - reject if not in team selection phase
        if self.draft.phase != DraftPhase.TEAM_SELECTION:
            await interaction.response.send_message(
                "팀 선택 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # In test mode, allow the real user to select for both teams
        if self.draft.is_test_mode and user_id == self.draft.real_user_id:
            # Real user can pick for any captain in test mode
            pass
        elif user_id != self.draft.current_picking_captain:
            await interaction.response.send_message(
                "지금은 네 차례가 아니야.", ephemeral=True
            )
            return
        
        # CRITICAL: Check if captain already completed their selections for this round
        current_captain = self.draft.current_picking_captain
        current_round = self.draft.team_selection_round
        if (current_captain in self.draft.team_selection_progress and 
            current_round in self.draft.team_selection_progress[current_captain] and
            self.draft.team_selection_progress[current_captain][current_round]):
            await interaction.response.send_message(
                "이번 라운드 선택을 이미 완료했어. 더 이상 선택할 수 없어.", ephemeral=True
            )
            return
        
        selected_player_id = int(self.values[0])
        target_player = self.draft.players[selected_player_id]
        current_captain = self.draft.current_picking_captain
        
        # Add to pending selections instead of immediately assigning
        if current_captain not in self.draft.pending_team_selections:
            self.draft.pending_team_selections[current_captain] = []
        
        # Check if player is already in pending selections
        if selected_player_id in self.draft.pending_team_selections[current_captain]:
            await interaction.response.send_message(
                f"**{target_player.username}**은(는) 이미 선택했어.", ephemeral=True
            )
            return
        
        # Check pick limit for this round
        round_info = self.bot_commands.team_selection_patterns[self.draft.team_size][self.draft.team_selection_round - 1]
        is_first_pick = current_captain == self.draft.first_pick_captain
        max_picks = round_info["first_pick"] if is_first_pick else round_info["second_pick"]
        current_pending = len(self.draft.pending_team_selections[current_captain])
        
        if current_pending >= max_picks:
            await interaction.response.send_message(
                f"이번 라운드에서는 최대 {max_picks}명까지만 선택할 수 있어.", ephemeral=True
            )
            return
        
        # Add to pending selections
        self.draft.pending_team_selections[current_captain].append(selected_player_id)
        
        captain_team = self.draft.players[current_captain].team
        pending_count = len(self.draft.pending_team_selections[current_captain])
        
        await interaction.response.send_message(
            f"**{target_player.username}**을(를) 팀 {captain_team} 후보로 선택했어! "
            f"({pending_count}/{max_picks})\n"
            f"확정하려면 '선택 확정' 버튼을 눌러줘.", 
            ephemeral=True
        )
        
        # Update the team selection interface to show pending selections and confirmation button
        await self.bot_commands._refresh_team_selection_interface(self.draft)
    
    async def _auto_complete_team_selection(self) -> None:
        """Auto-complete team selection in test mode"""
        
        # Get all unassigned players (excluding captains)
        unassigned_players = [
            player for player in self.draft.players.values()
            if player.team is None and not player.is_captain
        ]
        
        # Assign remaining players randomly to teams
        team1_count = sum(1 for p in self.draft.players.values() if p.team == 1)
        team2_count = sum(1 for p in self.draft.players.values() if p.team == 2)
        
        for player in unassigned_players:
            # Assign to team with fewer members, or randomly if equal
            if team1_count < team2_count:
                player.team = 1
                team1_count += 1
            elif team2_count < team1_count:
                player.team = 2
                team2_count += 1
            else:
                # Equal count, assign randomly
                team = random.choice([1, 2])
                player.team = team
                if team == 1:
                    team1_count += 1
                else:
                    team2_count += 1





class JoinDraftView(discord.ui.View):
    """Join/Leave buttons to collect players before starting a draft"""
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=3600.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.add_item(JoinButton())
        self.add_item(LeaveButton())
        self.add_item(ForceStartButton())

    async def on_timeout(self) -> None:
        # If timed out without starting, clean up
        channel_id = self.draft.channel_id
        if channel_id in self.bot_commands.active_views:
            try:
                await self.bot_commands._cleanup_views(channel_id)
            except Exception:
                pass


class JoinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="참가", style=discord.ButtonStyle.success, custom_id="join")
    async def callback(self, interaction: discord.Interaction) -> None:
        view: JoinDraftView = self.view
        draft = view.draft
        user = interaction.user
        if user.bot:
            await interaction.response.send_message("봇은 참가할 수 없어", ephemeral=True)
            return
        if draft.join_target_total_players is None:
            await interaction.response.send_message("이미 시작되었거나 잘못된 세션이야", ephemeral=True)
            return
        if user.id in draft.join_user_ids:
            await interaction.response.send_message("이미 참가했어", ephemeral=True)
            return
        draft.join_user_ids.add(user.id)
        # Update embed
        await update_join_embed(view)
        await interaction.response.defer()  # acknowledge silently
        # Auto-start when full
        if len(draft.join_user_ids) >= (draft.join_target_total_players or 0):
            await view.bot_commands._finalize_join_and_start(draft, starter_interaction=interaction)


class LeaveButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="취소", style=discord.ButtonStyle.secondary, custom_id="leave")
    async def callback(self, interaction: discord.Interaction) -> None:
        view: JoinDraftView = self.view
        draft = view.draft
        user = interaction.user
        if draft.join_target_total_players is None:
            await interaction.response.send_message("이미 시작되었거나 잘못된 세션이야", ephemeral=True)
            return
        if user.id not in draft.join_user_ids:
            await interaction.response.send_message("참가 상태가 아니야", ephemeral=True)
            return
        draft.join_user_ids.discard(user.id)
        await update_join_embed(view)
        await interaction.response.send_message("참가 취소했어", ephemeral=True)


class ForceStartButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="강제 시작", style=discord.ButtonStyle.primary, custom_id="force_start")
    async def callback(self, interaction: discord.Interaction) -> None:
        view: JoinDraftView = self.view
        draft = view.draft
        user = interaction.user
        # Permission: starter or bot owner can force start
        is_owner = False
        try:
            if isinstance(interaction.client, commands.Bot):
                is_owner = await interaction.client.is_owner(user)
        except Exception:
            is_owner = False
        if user.id != draft.started_by_user_id and not is_owner:
            await interaction.response.send_message("시작자만 강제 시작할 수 있어", ephemeral=True)
            return
        if len(draft.join_user_ids) < 2 or (len(draft.join_user_ids) % 2) != 0:
            await interaction.response.send_message("짝수 인원이 필요해", ephemeral=True)
            return
        await view.bot_commands._finalize_join_and_start(draft, starter_interaction=interaction)


async def update_join_embed(view: 'JoinDraftView') -> None:
    draft = view.draft
    channel = view.bot_commands.bot.get_channel(draft.channel_id)
    if not channel or not draft.join_message_id:
        return
    try:
        msg = await channel.fetch_message(draft.join_message_id)
    except Exception:
        return
    total = draft.join_target_total_players or 0
    names: List[str] = []
    guild = channel.guild if hasattr(channel, 'guild') else None
    for uid in draft.join_user_ids:
        name = str(uid)
        try:
            if guild:
                member = guild.get_member(uid)
                if member:
                    name = member.display_name
        except Exception:
            pass
        names.append(name)
    embed = msg.embeds[0] if msg.embeds else discord.Embed(color=INFO_COLOR)
    embed.title = f"🏁 드래프트 참가 모집 ({draft.team_size}v{draft.team_size})"
    embed.description = "아래 버튼을 눌러 참가하거나 취소해. 인원이 차면 자동으로 진행돼."
    embed.color = INFO_COLOR
    value_list = "\n".join([f"• {n}" for n in names]) if names else "없음"
    # rebuild fields
    embed.clear_fields()
    embed.add_field(name="필요 인원", value=f"{len(draft.join_user_ids)}/{total}")
    embed.add_field(name="참가자", value=value_list, inline=False)
    await msg.edit(embed=embed, view=view)


class FinishGameView(discord.ui.View):
    """View to finish the game and record outcome"""
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=7200.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.add_item(FinishGameButton())


class SimulationFinishView(discord.ui.View):
    """View to submit a completed simulation roster by an experienced captain"""
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=3600.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.add_item(SimulationSubmitButton())


class SimulationSubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🧪 시뮬 결과 제출", style=discord.ButtonStyle.success, custom_id="submit_simulation")

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SimulationFinishView = self.view  # type: ignore
        draft = view.draft
        user = interaction.user
        # Only the simulation author (experienced captain) or bot owner can submit
        is_owner = False
        try:
            if isinstance(interaction.client, commands.Bot):
                is_owner = await interaction.client.is_owner(user)
        except Exception:
            is_owner = False
        if user.id != (draft.simulation_author_id or 0) and not is_owner:
            await interaction.response.send_message("시뮬레이션을 시작한 팀장만 제출할 수 있어", ephemeral=True)
            return

        # Persist the simulated balanced roster using MatchRecorder with simulation flags
        try:
            match_id = draft.match_id or f"{draft.guild_id}:{draft.channel_id}:{int(time.time())}"
            draft.match_id = match_id
            team1_players = [p for p in draft.players.values() if p.team == 1]
            team2_players = [p for p in draft.players.values() if p.team == 2]

            def _build_features(team_players: List[Player]) -> List[PlayerFeature]:
                features: List[PlayerFeature] = []
                roster = []
                try:
                    roster = view.bot_commands.roster_store.load(draft.guild_id)
                except Exception:
                    roster = []
                for p in team_players:
                    rp = next((r for r in roster if r.user_id == p.user_id), None)
                    features.append(
                        PlayerFeature(
                            user_id=p.user_id,
                            display_name=p.username,
                            rating=(rp.rating if rp else None),
                            servant=draft.confirmed_servants.get(p.user_id),
                            is_captain=p.is_captain,
                            pick_order=None,
                        )
                    )
                return features

            record = view.bot_commands.match_recorder.write_prematch(
                match_id=match_id,
                guild_id=draft.guild_id,
                channel_id=draft.channel_id,
                team_size=draft.team_size,
                captains=[uid for uid, pl in draft.players.items() if pl.is_captain],
                team1=_build_features(team1_players),
                team2=_build_features(team2_players),
                bans=sorted(list(draft.banned_servants)) if draft.banned_servants else [],
                mode_name="sim_balanced",
                sim_session=getattr(draft, "simulation_session_id", None),
                author_id=getattr(draft, "simulation_author_id", None),
                is_simulation=True,
                sim_author_captain=getattr(draft, "simulation_author_id", None),
                sim_note="expert_balanced",
                draft_type="simulation",
                balance_algorithm=(draft.auto_balance_result.get("algorithm") if getattr(draft, "auto_balance_result", None) else None),
                predicted_balance_score=(draft.auto_balance_result.get("balance_score") if getattr(draft, "auto_balance_result", None) else None),
                predicted_confidence=(draft.auto_balance_result.get("confidence") if getattr(draft, "auto_balance_result", None) else None),
                processing_time=float((draft.auto_balance_result or {}).get("processing_time", 0.0)) if hasattr(draft, 'auto_balance_result') else 0.0,
                auto_balance_used=(True if getattr(draft, "auto_balance_result", None) else False),
            )
            # Enrich with flags if available
            try:
                record.is_simulation = True  # type: ignore[attr-defined]
                record.sim_author_captain = draft.simulation_author_id  # type: ignore[attr-defined]
                record.sim_note = "expert_balanced"  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as e:
            await interaction.response.send_message("제출 중 문제가 발생했어", ephemeral=True)
            return

        # Auto-update preferred_servants based on this simulation roster
        try:
            roster = view.bot_commands.roster_store.load(draft.guild_id)
            rp_map = {rp.user_id: rp for rp in roster}
            for p in team1_players + team2_players:
                char = draft.confirmed_servants.get(p.user_id)
                if not char:
                    continue
                rp = rp_map.get(p.user_id)
                if not rp:
                    rp = RosterPlayer(user_id=p.user_id, display_name=str(p.user_id))
                    rp_map[p.user_id] = rp
                prefs = getattr(rp, 'preferred_servants', []) or []
                if char not in prefs:
                    prefs.append(char)
                    rp.preferred_servants = prefs
            view.bot_commands.roster_store.add_or_update(draft.guild_id, list(rp_map.values()))
        except Exception as _e:
            logger.info(f"Preferred-servants auto-update (simulation) skipped: {_e}")

        await interaction.response.send_message("시뮬레이션 결과를 저장했어! 고마워.", ephemeral=True)
        # Disable the view to prevent duplicate submissions
        try:
            channel = view.bot_commands._get_draft_channel(draft)
            if channel:
                async for msg in channel.history(limit=10):
                    if msg.embeds and msg.author == view.bot_commands.bot.user:
                        try:
                            await msg.edit(view=None)
                        except Exception:
                            pass
                        break
        except Exception:
            pass


class FinishGameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="경기 종료 및 결과 기록", style=discord.ButtonStyle.danger, custom_id="finish_game")
    async def callback(self, interaction: discord.Interaction) -> None:
        view: FinishGameView = self.view
        draft = view.draft
        user = interaction.user
        if draft.outcome_recorded:
            await interaction.response.send_message("이미 결과가 기록되었어", ephemeral=True)
            return
        # Permission: starter or bot owner only
        is_owner = False
        try:
            if isinstance(interaction.client, commands.Bot):
                is_owner = await interaction.client.is_owner(user)
        except Exception:
            is_owner = False
        if user.id != (draft.started_by_user_id or 0) and not is_owner:
            await interaction.response.send_message("시작자만 결과를 기록할 수 있어", ephemeral=True)
            return
        # Prompt modal for score input like 12:8
        await interaction.response.send_modal(GameResultModal(draft, view.bot_commands))


class GameResultModal(discord.ui.Modal, title="경기 결과 입력"):
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=300.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.score_input = discord.ui.TextInput(label="팀1 점수(왼쪽):팀2 점수(오른쪽) (예: 12:8)", placeholder="12:8", required=True, max_length=10)
        self.add_item(self.score_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text = str(self.score_input.value).strip()
        import re
        m = re.match(r"^(\d{1,2})\s*[:：]\s*(\d{1,2})$", text)
        if not m:
            await interaction.response.send_message("형식이 올바르지 않아. 예: 12:8", ephemeral=True)
            return
        a = int(m.group(1))
        b = int(m.group(2))
        if a == b:
            await interaction.response.send_message("무승부는 허용되지 않아", ephemeral=True)
            return
        if a != 12 and b != 12:
            await interaction.response.send_message("12점에 도달한 팀이 있어야 해", ephemeral=True)
            return
        winner = 1 if a > b else 2
        score_str = f"{a}:{b}"
        # Record outcome (idempotent)
        try:
            match_id = self.draft.match_id or f"{self.draft.guild_id}:{self.draft.channel_id}:"
            if not self.draft.outcome_recorded:
                self.bot_commands.match_recorder.write_outcome(match_id=match_id, winner=winner, score=score_str)
                self.draft.outcome_recorded = True
        except Exception as e:
            await interaction.response.send_message("결과 저장에 실패했어", ephemeral=True)
            return
        await interaction.response.send_message("결과를 기록했어!", ephemeral=True)
        # Disable finish view so it can't be used again
        try:
            channel = self.bot_commands._get_draft_channel(self.draft)
            if channel and self.draft.finish_view_message_id:
                msg = await channel.fetch_message(self.draft.finish_view_message_id)
                await msg.edit(view=None)
        except Exception:
            pass
        # Cleanup draft now
        await self.bot_commands._final_cleanup_after_outcome(self.draft)








class EphemeralSelectionView(discord.ui.View):
    """View with single button for all players to open their private selection interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        
        # Add single generic button that all players can use
        button = GenericSelectionInterfaceButton()
        self.add_item(button)


class GenericSelectionInterfaceButton(discord.ui.Button):
    """Single button for all players to open their private selection interface"""
    
    def __init__(self):
        super().__init__(
            label="🎯 내 서번트 선택하기",
            style=discord.ButtonStyle.primary,
            custom_id="open_my_selection",
            emoji="⚔️",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private selection interface for the player"""
        try:
            user_id = interaction.user.id
            view: EphemeralSelectionView = self.view
            
            logger.info(f"Generic selection button clicked by user {user_id}")
            
            # Validate user exists
            if not interaction.user:
                logger.warning(f"No user found in interaction")
                await interaction.response.send_message(
                    "인터페이스 인증에 실패했어. 다시 시도해줘.", ephemeral=True
                )
                return
            
            # Validate user is in draft
            if user_id not in view.draft.players:
                logger.warning(f"User {user_id} not in draft but tried to access interface")
                await interaction.response.send_message(
                    "드래프트 참가자만 선택 인터페이스를 사용할 수 있어.", ephemeral=True
                )
                return
            
            # During reselection phase, only allow conflicted players to re-select
            if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
                conflicted_players = set()
                for user_ids in view.draft.conflicted_servants.values():
                    conflicted_players.update(user_ids)
                
                # In test mode, allow real user to access any player's interface
                if user_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                    player_name = view.draft.players[user_id].username
                    await interaction.response.send_message(
                        f"**{player_name}**은(는) 재선택 대상이 아니야.\n"
                        "중복으로 인해 재선택이 필요한 플레이어만 변경할 수 있어.", ephemeral=True
                    )
                    return
            
            # Check if already completed
            player_name = view.draft.players[user_id].username
            current_selection = view.draft.players[user_id].selected_servant
            
            if view.draft.selection_progress.get(user_id, False):
                logger.info(f"Player {user_id} ({player_name}) already completed selection: {current_selection}")
                
                if current_selection:
                    await interaction.response.send_message(
                        f"이미 선택을 완료했어: **{current_selection}**\n"
                        "더 이상 변경할 수 없어.", 
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "선택을 완료했지만 서번트가 없어. 시스템 오류일 수 있으니 관리자에게 문의해줘.", 
                        ephemeral=True
                    )
                return
            
            # Open private selection interface
            logger.info(f"Opening selection interface for player {user_id} ({player_name})")
            private_view = PrivateSelectionView(view.draft, view.bot_commands, user_id)
            
            await interaction.response.send_message(
                f"**{player_name}의 개인 서번트 선택**\n"
                "원하는 서번트를 한 명 선택해줘.\n"
                "다른 플레이어는 네 선택을 볼 수 없어.",
                ephemeral=True,
                view=private_view
            )
            logger.info(f"Successfully sent ephemeral selection interface to player {user_id} ({player_name})")
            
        except Exception as e:
            logger.error(f"Error in selection interface button callback: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "선택 인터페이스 열기에 실패했어. 다시 시도해줘.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "선택 인터페이스 열기에 실패했어. 다시 시도해줘.", ephemeral=True
                    )
            except Exception as followup_error:
                logger.error(f"Failed to send error message: {followup_error}", exc_info=True)


class PrivateSelectionView(discord.ui.View):
    """Private selection interface for individual players"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', user_id: int):
        player_name = draft.players[user_id].username if user_id in draft.players else "Unknown"
        logger.info(f"Initializing PrivateSelectionView for user {user_id} ({player_name})")
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.user_id = user_id
        self.current_category = "세이버"
        
        # Initialize with None to prevent stale data issues - force fresh selection
        # This prevents character mismatch bugs when multiple UI instances exist
        self.selected_servant = None
        
        # Log current draft state for debugging
        current_selection = draft.players[user_id].selected_servant if user_id in draft.players else None
        logger.info(f"User {user_id} ({player_name}) - Current draft selection: {current_selection}, UI initialized with: {self.selected_servant}")
        
        try:
            # Add category buttons
            logger.info(f"Adding category buttons for user {user_id}")
            self._add_category_buttons()
            logger.info(f"Added {len([c for c in self.children if hasattr(c, 'category')])} category buttons")
            
            # Add character dropdown for current category
            logger.info(f"Adding character dropdown for category {self.current_category}")
            self._add_character_dropdown()
            logger.info(f"Added character dropdown, total children: {len(self.children)}")
            
            # Add confirmation button
            logger.info(f"Adding confirmation button")
            self._add_confirmation_button()
            logger.info(f"PrivateSelectionView initialization complete, total UI elements: {len(self.children)}")
            
        except Exception as e:
            logger.error(f"Error during PrivateSelectionView initialization: {e}", exc_info=True)
            raise
    
    async def on_timeout(self) -> None:
        """Handle interface timeout - add reopen button to public message"""
        try:
            # Add reopen functionality if user hasn't completed selection yet
            if not self.draft.selection_progress.get(self.user_id, False):
                await self.bot_commands._add_reopen_selection_interface_button(self.draft, self.user_id)
        except Exception as e:
            logger.error(f"Error handling selection interface timeout: {e}")

    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):
            button = PrivateSelectionCategoryButton(category, i, self.user_id)
            self.add_item(button)

    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, (PrivateSelectionCharacterDropdown, EmptySelectionDropdown)):
                self.remove_item(item)
        
        # Get available characters for current category (exclude banned and confirmed)
        excluded_servants = self.draft.banned_servants.copy()
        
        # During reselection, also exclude confirmed servants to prevent infinite loops
        if self.draft.phase == DraftPhase.SERVANT_RESELECTION:
            excluded_servants.update(self.draft.confirmed_servants.values())
        
        available_in_category = [
            char for char in self.draft.servant_categories[self.current_category]
            if char not in excluded_servants
        ]
        
        # Check if category has any available characters
        if not available_in_category:
            # Create a disabled dropdown showing no characters available
            dropdown = EmptySelectionDropdown(self.current_category)
            self.add_item(dropdown)
        else:
            # Create normal dropdown with available characters
            dropdown = PrivateSelectionCharacterDropdown(
                self.draft, self.bot_commands, available_in_category, 
                self.current_category, self.user_id
            )
            self.add_item(dropdown)

    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmSelectionButton(self.user_id)
        self.add_item(button)

    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        selection_text = f"현재 선택: {self.selected_servant if self.selected_servant else '없음'}"
        
        embed = discord.Embed(
            title=f"⚔️ 서번트 선택 - {new_category}",
            description=f"**현재 카테고리: {new_category}**\n{selection_text}",
            color=INFO_COLOR
        )
        
        # Show characters in current category with status
        chars_in_category = self.draft.servant_categories[new_category]
        char_list = []
        for char in chars_in_category:
            if char in self.draft.banned_servants:
                char_list.append(f"❌ {char}")
            elif char in self.draft.confirmed_servants.values() and self.draft.phase == DraftPhase.SERVANT_RESELECTION:
                char_list.append(f"🔒 {char}")
            else:
                char_list.append(f"• {char}")
        
        embed.add_field(name=f"{new_category} 서번트 목록", value="\n".join(char_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


class PrivateSelectionCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private selection interface"""
    
    def __init__(self, category: str, index: int, user_id: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_selection_category_{category}_{user_id}",
            row=index // 4
        )
        self.category = category
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        logger.info(f"Category '{self.category}' clicked by user {user_id}")
        
        # Enhanced validation to prevent race condition issues
        if not interaction.user:
            logger.warning(f"No user found in category interaction for user {view.user_id}")
            await interaction.response.send_message(
                "인터페이스 인증에 실패했어. 다시 시도해줘.", ephemeral=True
            )
            return
        
        # CRITICAL: Validate user is interacting with their own interface
        # This prevents cross-contamination between different users' selection interfaces
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            # In test mode, allow the real user to interact with any interface
            pass
        elif user_id != view.user_id:
            # User is trying to interact with someone else's interface
            actual_user_name = view.draft.players[view.user_id].username if view.user_id in view.draft.players else "Unknown"
            clicking_user_name = view.draft.players[user_id].username if user_id in view.draft.players else "Unknown" 
            logger.warning(f"User {user_id} ({clicking_user_name}) tried to interact with user {view.user_id} ({actual_user_name})'s category interface")
            # Clear any potentially contaminated state
            view.selected_servant = None
            await interaction.response.send_message(
                f"이 인터페이스는 **{actual_user_name}**용이야!\n"
                f"**{clicking_user_name}**의 선택 버튼을 눌러서 자신의 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        # SIMPLIFIED SECURITY MODEL: State validation without complex session management
        # 
        # Security is provided by 2 simple layers:
        # 1. Discord's ephemeral messages (only recipient can see/interact)
        # 2. State validation (below) - prevents wrong phase/completed interactions
        #
        # This eliminates race conditions while maintaining all necessary security
        
        # 1. Phase validation - prevent interaction if wrong phase
        if view.draft.phase not in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
            await interaction.response.send_message(
                "이 선택 단계는 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", 
                ephemeral=True
            )
            return
        
        # 2. Completion validation - prevent changes after confirmation
        if view.draft.selection_progress.get(view.user_id, False):
            await interaction.response.send_message(
                "이미 선택을 완료했어. 더 이상 변경할 수 없어.", 
                ephemeral=True
            )
            return
        
        # 3. Reselection validation - during reselection, only allow conflicted players
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            conflicted_players = set()
            for user_ids in view.draft.conflicted_servants.values():
                conflicted_players.update(user_ids)
            
            if view.user_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                user_name = view.draft.players[view.user_id].username
                await interaction.response.send_message(
                    f"**{user_name}**은(는) 재선택 대상이 아니야.\n"
                    "중복으로 인해 재선택이 필요한 플레이어만 변경할 수 있어.", ephemeral=True
                )
                return
        
        await view.update_category(self.category, interaction)





class ConfirmSelectionButton(discord.ui.Button):
    """Button to confirm servant selection"""
    
    def __init__(self, user_id: int):
        super().__init__(
            label="선택 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_selection_{user_id}",
            emoji="✅",
            row=4
        )
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Confirm servant selection"""
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        user_name = view.draft.players[self.user_id].username if self.user_id in view.draft.players else "Unknown"
        logger.info(f"Confirmation attempt by user {user_id} ({user_name}) - selected: {view.selected_servant}")
        
        # Enhanced validation to prevent race condition issues
        if not interaction.user:
            logger.warning(f"No user found in confirmation interaction for user {self.user_id}")
            await interaction.response.send_message(
                "인터페이스 인증에 실패했어. 다시 시도해줘.", ephemeral=True
            )
            return
        
        # Validate user is in draft
        if user_id not in view.draft.players:
            await interaction.response.send_message(
                "드래프트 참가자만 선택 인터페이스를 사용할 수 있어.", ephemeral=True
            )
            return
        
        # CRITICAL: Validate user is confirming their own selection
        if user_id != self.user_id and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
            # This should not happen with proper ephemeral message isolation
            actual_user_name = view.draft.players[self.user_id].username if self.user_id in view.draft.players else "Unknown"
            clicking_user_name = view.draft.players[user_id].username if user_id in view.draft.players else "Unknown" 
            logger.warning(f"SECURITY BREACH: User {user_id} ({clicking_user_name}) tried to confirm selection for user {self.user_id} ({actual_user_name})")
            await interaction.response.send_message(
                f"이 확정 버튼은 **{actual_user_name}**용이야!\n"
                f"**{clicking_user_name}**의 선택 버튼을 눌러서 자신의 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        # During reselection phase, only allow conflicted players to confirm
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            conflicted_players = set()
            for user_ids in view.draft.conflicted_servants.values():
                conflicted_players.update(user_ids)
            
            # In test mode, allow real user to confirm for any user for testing
            if self.user_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                await interaction.response.send_message(
                    f"**{user_name}**은(는) 재선택 대상이 아니야.\n"
                    "중복으로 인해 재선택이 필요한 플레이어만 변경할 수 있어.", ephemeral=True
                )
                return
        
        # Simple state validation
        # 1. Completion validation - prevent double confirmation
        if view.draft.selection_progress.get(self.user_id, False):
            current_selection = view.draft.players[self.user_id].selected_servant
            logger.info(f"User {self.user_id} ({user_name}) already completed, current selection: {current_selection}")
            await interaction.response.send_message(
                f"이미 선택을 완료했어: **{current_selection}**", ephemeral=True
            )
            return
        
        if not view.selected_servant:
            await interaction.response.send_message(
                "서번트를 먼저 선택해줘.",
                ephemeral=True
            )
            return
        
        # ADDITIONAL SAFETY: Verify the selected servant is available and valid
        if view.selected_servant in view.draft.banned_servants:
            logger.warning(f"User {self.user_id} ({user_name}) tried to confirm banned servant: {view.selected_servant}")
            await interaction.response.send_message(
                f"**{view.selected_servant}**은(는) 밴된 서번트야. 다른 서번트를 선택해줘.",
                ephemeral=True
            )
            view.selected_servant = None  # Reset invalid selection
            return
        
        # During reselection, ensure servant isn't already confirmed by someone else
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            if view.selected_servant in view.draft.confirmed_servants.values():
                logger.warning(f"User {self.user_id} ({user_name}) tried to confirm already taken servant during reselection: {view.selected_servant}")
                await interaction.response.send_message(
                    f"**{view.selected_servant}**은(는) 이미 다른 플레이어가 선택했어. 다른 서번트를 선택해줘.",
                    ephemeral=True
                )
                view.selected_servant = None  # Reset invalid selection
                return
        
        # Save selection
        view.draft.players[self.user_id].selected_servant = view.selected_servant
        view.draft.selection_progress[self.user_id] = True
        
        logger.info(f"User {self.user_id} ({user_name}) confirmed selection: {view.selected_servant}")
        
        await interaction.response.send_message(
            f"✅ **선택 완료!**\n"
            f"**{user_name}**이(가) **{view.selected_servant}**을(를) 선택했어.\n"
            "다른 플레이어들이 완료할 때까지 기다려줘.",
            ephemeral=True
        )
        
        # Update public progress
        await view.bot_commands._update_selection_progress_message(view.draft)
        
        # Check completion based on current phase
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            # During reselection: check if all conflicted players have reselected
            await view.bot_commands._check_reselection_completion(view.draft)
        else:
            # During initial selection: check if all players completed
            if all(view.draft.selection_progress.values()):
                # Auto-complete remaining selections for test mode
                if view.draft.is_test_mode:
                    await view.bot_commands._auto_complete_test_selections(view.draft)
                
                await view.bot_commands._reveal_servant_selections(view.draft)


class ReopenBanInterfaceView(discord.ui.View):
    """View with reopen button for expired ban interfaces"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', captain_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.captain_id = captain_id
        
        captain_name = draft.players[captain_id].username
        button = ReopenBanInterfaceButton(captain_id, captain_name)
        self.add_item(button)


class ReopenBanInterfaceButton(discord.ui.Button):
    """Button to reopen expired ban interface"""
    
    def __init__(self, captain_id: int, captain_name: str):
        super().__init__(
            label=f"{captain_name} - 인터페이스 다시 열기",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reopen_ban_{captain_id}",
            emoji="🔄"
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Reopen ban interface for this captain"""
        view: ReopenBanInterfaceView = self.view
        
        # In test mode, allow the real user to access any captain's interface
        if view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id:
            pass
        elif interaction.user.id != self.captain_id:
            await interaction.response.send_message(
                "팀장만 밴 인터페이스를 사용할 수 있어.", ephemeral=True
            )
            return
            
        # Check if already completed bans
        if view.draft.captain_ban_progress.get(self.captain_id, False):
            await interaction.response.send_message(
                "이미 밴을 완료했어.", ephemeral=True
            )
            return
        
        # Note: This is deprecated legacy ban interface code
        
        # This old interface has been removed - redirect to error message
        await interaction.response.send_message(
            "⚠️ **이 인터페이스는 더 이상 사용되지 않아**\n"
            "새로운 순차적 밴 시스템을 사용해줘.",
            ephemeral=True
        )


class GenericReopenSelectionView(discord.ui.View):
    """View with single reopen button for all players"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        
        # Single generic reopen button for all players
        button = GenericReopenSelectionButton()
        self.add_item(button)


class GenericReopenSelectionButton(discord.ui.Button):
    """Single reopen button for all players"""
    
    def __init__(self):
        super().__init__(
            label="🔄 내 서번트 선택 다시 열기",
            style=discord.ButtonStyle.secondary,
            custom_id="reopen_my_selection",
            emoji="⚔️"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Reopen selection interface for the user"""
        try:
            user_id = interaction.user.id
            view: GenericReopenSelectionView = self.view
            
            # Validate user exists
            if not interaction.user:
                logger.warning(f"No user found in generic reopen interaction")
                await interaction.response.send_message(
                    "인터페이스 인증에 실패했어. 다시 시도해줘.", ephemeral=True
                )
                return
            
            # Validate user is in draft
            if user_id not in view.draft.players:
                await interaction.response.send_message(
                    "드래프트 참가자만 선택 인터페이스를 사용할 수 있어.", ephemeral=True
                )
                return
            
            # Check if already completed
            if view.draft.selection_progress.get(user_id, False):
                current_selection = view.draft.players[user_id].selected_servant
                await interaction.response.send_message(
                    f"이미 선택을 완료했어: **{current_selection}**", ephemeral=True
                )
                return
            
            # During reselection phase, only allow conflicted players to reopen interface
            if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
                conflicted_players = set()
                for user_ids in view.draft.conflicted_servants.values():
                    conflicted_players.update(user_ids)
                
                if user_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                    player_name = view.draft.players[user_id].username
                    await interaction.response.send_message(
                        f"**{player_name}**은(는) 재선택 대상이 아니야.\n"
                        "중복으로 인해 재선택이 필요한 플레이어만 인터페이스를 다시 열 수 있어.", ephemeral=True
                    )
                    return
            
            player_name = view.draft.players[user_id].username
            
            # Create private selection interface
            private_view = PrivateSelectionView(view.draft, view.bot_commands, user_id)
            
            await interaction.response.send_message(
                f"**{player_name}의 개인 서번트 선택 (재시도)**\n"
                "원하는 서번트를 한 명 선택해줘.\n"
                "다른 플레이어는 네 선택을 볼 수 없어.",
                ephemeral=True,
                view=private_view
            )
            logger.info(f"Successfully reopened selection interface for player {user_id} ({player_name})")
            
        except Exception as e:
            logger.error(f"Error in generic reopen selection button callback: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "선택 인터페이스 열기에 실패했어. 다시 시도해줘.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "선택 인터페이스 열기에 실패했어. 다시 시도해줘.", ephemeral=True
                    )
            except Exception as followup_error:
                logger.error(f"Failed to send error message: {followup_error}", exc_info=True)


class ReopenSelectionInterfaceView(discord.ui.View):
    """View with reopen button for expired selection interfaces (LEGACY - kept for compatibility)"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', user_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.user_id = user_id
        
        user_name = draft.players[user_id].username
        button = ReopenSelectionInterfaceButton(user_id, user_name)
        self.add_item(button)


class ReopenSelectionInterfaceButton(discord.ui.Button):
    """Button to reopen expired selection interface"""
    
    def __init__(self, user_id: int, user_name: str):
        super().__init__(
            label=f"{user_name} - 인터페이스 다시 열기",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reopen_selection_{user_id}",
            emoji="🔄"
        )
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Reopen selection interface for this player"""
        view: ReopenSelectionInterfaceView = self.view
        user_id = interaction.user.id
        
        # Validate user exists
        if not interaction.user:
            logger.warning(f"No user found in reopen interaction")
            await interaction.response.send_message(
                "인터페이스 인증에 실패했어. 다시 시도해줘.", ephemeral=True
            )
            return
        
        # Validate user is in draft
        if user_id not in view.draft.players:
            await interaction.response.send_message(
                "드래프트 참가자만 선택 인터페이스를 사용할 수 있어.", ephemeral=True
            )
            return
        
        # FIXED: Validate user is clicking their own reopen button
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            # In test mode, allow real user to reopen any interface
            actual_user_id = self.user_id
        elif user_id == self.user_id:
            # Normal case: user clicking their own reopen button
            actual_user_id = user_id
        else:
            # User clicked someone else's reopen button
            button_user_name = view.draft.players[self.user_id].username
            clicking_user_name = view.draft.players[user_id].username
            await interaction.response.send_message(
                f"이 버튼은 **{button_user_name}**용이야!\n"
                f"**{clicking_user_name}**의 인터페이스 다시 열기 버튼을 찾아서 눌러줘.", 
                ephemeral=True
            )
            return
        
        # Check if already completed (using correct user ID)
        if view.draft.selection_progress.get(actual_user_id, False):
            await interaction.response.send_message(
                "이미 선택을 완료했어.", ephemeral=True
            )
            return
        
        # During reselection phase, only allow conflicted players to reopen interface
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            conflicted_players = set()
            for user_ids in view.draft.conflicted_servants.values():
                conflicted_players.update(user_ids)
            
            # In test mode, allow real user to access any interface for testing
            if actual_user_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                user_name = view.draft.players[actual_user_id].username
                await interaction.response.send_message(
                    f"**{user_name}**은(는) 재선택 대상이 아니야.\n"
                    "중복으로 인해 재선택이 필요한 플레이어만 인터페이스를 다시 열 수 있어.", ephemeral=True
                )
                return
        
        user_name = view.draft.players[actual_user_id].username
        
        # Create private selection interface (using correct user ID)
        private_view = PrivateSelectionView(view.draft, view.bot_commands, actual_user_id)
        
        await interaction.response.send_message(
            f"**{user_name}의 개인 서번트 선택 (재시도)**\n"
            "원하는 서번트를 한 명 선택해줘.\n"
            "다른 플레이어는 네 선택을 볼 수 없어.",
            ephemeral=True,
            view=private_view
        )


class ReopenCaptainBanInterfaceView(discord.ui.View):
    """View with reopen button for expired captain ban interfaces"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', captain_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.captain_id = captain_id
        
        captain_name = draft.players[captain_id].username
        button = ReopenCaptainBanInterfaceButton(captain_id, captain_name)
        self.add_item(button)


class ReopenCaptainBanInterfaceButton(discord.ui.Button):
    """Button to reopen expired captain ban interface"""
    
    def __init__(self, captain_id: int, captain_name: str):
        super().__init__(
            label=f"{captain_name} - 인터페이스 다시 열기",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reopen_captain_ban_{captain_id}",
            emoji="🔄"
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Reopen captain ban interface for this captain"""
        view: ReopenCaptainBanInterfaceView = self.view
        
        # CRITICAL: Check if draft phase has moved beyond banning
        if view.draft.phase != DraftPhase.SERVANT_BAN:
            await interaction.response.send_message(
                "밴 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # Check if it's the current captain's turn
        if view.draft.current_banning_captain != self.captain_id:
            await interaction.response.send_message(
                "지금은 네 차례가 아니야. 순서를 기다려줘.", ephemeral=True
            )
            return
        
        # CRITICAL: Additional check - if captain already completed their ban AND it's no longer their turn
        if (view.draft.captain_ban_progress.get(self.captain_id, False) and 
            view.draft.current_banning_captain != self.captain_id):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            ban_text = current_bans[0] if current_bans else "없음"
            await interaction.response.send_message(
                f"이미 밴을 완료했어: **{ban_text}**\n"
                "완료된 밴은 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # In test mode, allow the real user to access any captain's interface
        if view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id:
            pass
        elif interaction.user.id != self.captain_id:
            await interaction.response.send_message(
                "팀장만 밴 인터페이스를 사용할 수 있어.", ephemeral=True
            )
            return
            
        # Check if already completed bans
        if view.draft.captain_ban_progress.get(self.captain_id, False):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            if current_bans and view.draft.current_banning_captain != self.captain_id:
                # Ban completed and it's no longer their turn - don't allow editing
                ban_text = current_bans[0]
                await interaction.response.send_message(
                    f"이미 밴을 완료했어: **{ban_text}**\n"
                    "밴이 공개된 후에는 변경할 수 없어.", 
                    ephemeral=True
                )
            else:
                # Either no bans recorded or still their turn
                await interaction.response.send_message(
                    "이미 밴을 완료했어.", ephemeral=True
                )
            return
        
        # Create private captain ban interface
        private_view = PrivateCaptainBanView(view.draft, view.bot_commands, self.captain_id)
        
        await interaction.response.send_message(
            "🚫 **개인 밴 인터페이스 (재시도)**\n"
            "밴하고 싶은 서번트를 **1명** 선택해줘.\n"
            "상대방은 네 선택을 볼 수 없어.",
            ephemeral=True,
            view=private_view
        )


class CaptainVotingView(discord.ui.View):
    """View for captain voting with buttons"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.user_votes: Dict[int, Set[int]] = {}  # user_id -> set of voted_user_ids
        
        # Create buttons for each player
        players = list(draft.players.values())
        for i, player in enumerate(players[:12]):  # Max 12 buttons
            button = CaptainVoteButton(player.user_id, player.username, i + 1)
            self.add_item(button)

    async def on_timeout(self) -> None:
        """Handle timeout - finalize voting"""
        await self._finalize_voting()

    async def _finalize_voting(self) -> None:
        """Finalize captain voting and proceed to next phase"""
        # Prevent timeout triggers from interfering with later phases
        if self.draft.phase != DraftPhase.CAPTAIN_VOTING:
            logger.warning(f"Captain voting timeout triggered during wrong phase: {self.draft.phase}")
            return
            
        # Count votes
        vote_counts = {}
        for player_id in self.draft.players.keys():
            vote_counts[player_id] = 0
        # Logging: snapshot of user->votes before counting
        try:
            votes_snapshot = {uid: sorted(list(votes)) for uid, votes in self.user_votes.items()}
            logger.info(f"[CaptainVote] finalize_snapshot channel={self.draft.channel_id} votes={votes_snapshot}")
        except Exception as e:
            logger.warning(f"[CaptainVote] finalize_snapshot_error: {e}")
        
        for votes in self.user_votes.values():
            for voted_player_id in votes:
                vote_counts[voted_player_id] += 1
        
        # Select top 2 vote getters as captains
        sorted_players = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        
        # For test mode: if there are ties or insufficient votes, randomly select from tied players
        if len(self.user_votes) <= 1:  # Test mode or very few votes
            # Get all players with the highest vote count
            max_votes = sorted_players[0][1] if sorted_players else 0
            top_players = [player_id for player_id, votes in sorted_players if votes == max_votes]
            
            # If we have ties or not enough clear winners, supplement with random selection
            if len(top_players) < 2:
                # Add remaining players for random selection
                remaining_players = [player_id for player_id, _ in sorted_players if player_id not in top_players]
                needed = 2 - len(top_players)
                if len(remaining_players) >= needed:
                    top_players.extend(random.sample(remaining_players, needed))
                else:
                    top_players.extend(remaining_players)
            elif len(top_players) > 2:
                # Too many ties, randomly select 2 from the tied players
                        top_players = random.sample(top_players, 2)
            
            self.draft.captains = top_players[:2]
        else:
            # Normal mode: select top 2 vote getters
            self.draft.captains = [sorted_players[0][0], sorted_players[1][0]]
        # Logging: vote counts and selected captains
        try:
            captain_names = [self.draft.players[cid].username for cid in self.draft.captains]
            logger.info(
                f"[CaptainVote] finalize_result channel={self.draft.channel_id} vote_counts={vote_counts} "
                f"captains={self.draft.captains}({captain_names})"
            )
        except Exception as e:
            logger.warning(f"[CaptainVote] finalize_result_logging_error: {e}")
        
        # Mark them as captains and initialize progress tracking
        for captain_id in self.draft.captains:
            self.draft.players[captain_id].is_captain = True
            self.draft.captain_ban_progress[captain_id] = False
        
        # Start servant ban phase
        self.draft.phase = DraftPhase.SERVANT_BAN
        
        if self.draft.is_test_mode:
            logger.info("Detected test mode - using new automated ban system")
            # Start the new ban phase which includes automated system bans and captain bans
            await self.bot_commands._start_servant_ban_phase(self.draft)
        else:
            logger.info("Detected normal mode - showing ban interface")
            # Normal mode - show ban interface
            await self.bot_commands._start_servant_ban_phase(self.draft)


class CaptainVoteButton(discord.ui.Button):
    """Button for voting for a captain"""
    
    def __init__(self, player_id: int, username: str, number: int):
        super().__init__(
            label=f"{number}. {username}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"vote_{player_id}"
        )
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle vote button click"""
        user_id = interaction.user.id
        view: CaptainVotingView = self.view
        
        # Validate current phase - reject if not in captain voting phase
        if view.draft.phase != DraftPhase.CAPTAIN_VOTING:
            await interaction.response.send_message(
                "캡틴 투표 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # Check if user is part of the draft
        if user_id not in view.draft.players:
            await interaction.response.send_message(
                "드래프트 참가자만 투표할 수 있어.", ephemeral=True
            )
            return
        
        # Initialize user votes if needed
        if user_id not in view.user_votes:
            view.user_votes[user_id] = set()
        # Logging: pre-click snapshot
        try:
            pre_votes = sorted(list(view.user_votes.get(user_id, set())))
            voter_name = view.draft.players.get(user_id).username if user_id in view.draft.players else "unknown"
            target_name = view.draft.players.get(self.player_id).username if self.player_id in view.draft.players else "unknown"
            msg_id = getattr(interaction.message, 'id', None)
            logger.info(
                f"[CaptainVote] click channel={view.draft.channel_id} user={user_id}({voter_name}) "
                f"target={self.player_id}({target_name}) pre={pre_votes} message={msg_id} view_id={id(view)}"
            )
        except Exception as e:
            logger.warning(f"[CaptainVote] click_logging_error: {e}")
        
        # Toggle vote
        if self.player_id in view.user_votes[user_id]:
            view.user_votes[user_id].remove(self.player_id)
            # Update progress tracking
            view.draft.captain_voting_progress[user_id] = len(view.user_votes[user_id])
            # Logging: cancellation
            try:
                post_votes = sorted(list(view.user_votes[user_id]))
                logger.info(
                    f"[CaptainVote] cancel channel={view.draft.channel_id} user={user_id} target={self.player_id} "
                    f"post={post_votes} count={len(post_votes)}"
                )
            except Exception as e:
                logger.warning(f"[CaptainVote] cancel_logging_error: {e}")
            await interaction.response.send_message(
                f"{view.draft.players[self.player_id].username}에 대한 투표를 취소했어.", 
                ephemeral=True
            )
        else:
            # Check vote limit (max 2 votes)
            if len(view.user_votes[user_id]) >= 2:
                # Logging: limit reached
                try:
                    current_votes = sorted(list(view.user_votes[user_id]))
                    logger.warning(
                        f"[CaptainVote] limit_reached channel={view.draft.channel_id} user={user_id} "
                        f"attempted_target={self.player_id} current={current_votes}"
                    )
                except Exception as e:
                    logger.warning(f"[CaptainVote] limit_logging_error: {e}")
                await interaction.response.send_message(
                    "최대 2명까지만 투표할 수 있어.", ephemeral=True
                )
                return
            
            view.user_votes[user_id].add(self.player_id)
            # Update progress tracking
            view.draft.captain_voting_progress[user_id] = len(view.user_votes[user_id])
            # Logging: cast
            try:
                post_votes = sorted(list(view.user_votes[user_id]))
                logger.info(
                    f"[CaptainVote] cast channel={view.draft.channel_id} user={user_id} target={self.player_id} "
                    f"post={post_votes} count={len(post_votes)}"
                )
            except Exception as e:
                logger.warning(f"[CaptainVote] cast_logging_error: {e}")
            await interaction.response.send_message(
                f"{view.draft.players[self.player_id].username}에게 투표했어.", 
                ephemeral=True
            )
        
        # Update progress message
        await view.bot_commands._update_captain_voting_progress_message(view.draft)
        
        # Check if voting should be completed
        should_complete = await view.bot_commands._check_voting_completion(view)
        if should_complete:
            await view._finalize_voting()


class EmptySelectionDropdown(discord.ui.Select):
    """Dropdown shown when no characters are available in a category"""
    
    def __init__(self, category: str):
        options = [
            discord.SelectOption(
                label="선택 가능한 서번트가 없어",
                value="empty",
                description=f"{category} 클래스의 모든 서번트가 금지됨",
                emoji="❌"
            )
        ]
        
        super().__init__(
            placeholder=f"{category} - 선택 불가",
            options=options,
            min_values=0,
            max_values=0,
            disabled=True,
            row=3
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """This should never be called since the dropdown is disabled"""
        await interaction.response.send_message(
            "이 카테고리는 모든 서번트가 밴되어서 선택할 수 없어.", ephemeral=True
        )


class PrivateSelectionCharacterDropdown(discord.ui.Select):
    """Dropdown for selecting characters in private interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', characters: List[str], category: str, user_id: int):
        self.draft = draft
        self.bot_commands = bot_commands
        self.category = category
        self.user_id = user_id
        
        current_selection = draft.players[user_id].selected_servant
        
        options = [
            discord.SelectOption(
                label=char, 
                value=char, 
                description=f"{category} 클래스",
                default=char == current_selection
            )
            for char in characters[:25]
        ]
        
        super().__init__(
            placeholder=f"{category} 서번트 선택...",
            options=options,
            min_values=1,
            max_values=1,
            row=3
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle character selection"""
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        # Enhanced validation to prevent race condition issues
        if not interaction.user:
            logger.warning(f"No user found in character dropdown interaction for user {self.user_id}")
            await interaction.response.send_message(
                "인터페이스 인증에 실패했어. 다시 시도해줘.", ephemeral=True
            )
            return
        
        # CRITICAL: Validate user is interacting with their own interface
        # This prevents cross-contamination between different users' selection interfaces
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            # In test mode, allow the real user to interact with any interface
            pass
        elif user_id != self.user_id:
            # User is trying to interact with someone else's interface
            actual_user_name = view.draft.players[self.user_id].username if self.user_id in view.draft.players else "Unknown"
            clicking_user_name = view.draft.players[user_id].username if user_id in view.draft.players else "Unknown" 
            logger.warning(f"User {user_id} ({clicking_user_name}) tried to interact with user {self.user_id} ({actual_user_name})'s interface")
            # Clear any potentially contaminated state
            view.selected_servant = None
            await interaction.response.send_message(
                f"이 인터페이스는 **{actual_user_name}**용이야!\n"
                f"**{clicking_user_name}**의 선택 버튼을 눌러서 자신의 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        # Simple state validation - no complex session management needed
        
        # 1. Phase validation - prevent interaction if wrong phase
        if view.draft.phase not in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
            await interaction.response.send_message(
                "이 선택 단계는 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", 
                ephemeral=True
            )
            return
        
        # 2. Completion validation - prevent changes after confirmation
        if view.draft.selection_progress.get(self.user_id, False):
            await interaction.response.send_message(
                "이미 선택을 완료했어. 더 이상 변경할 수 없어.", 
                ephemeral=True
            )
            return
        
        # Update selected servant
        view.selected_servant = self.values[0]
        
        await interaction.response.send_message(
            f"**{self.values[0]}** ({self.category})을(를) 선택했어!\n"
            "확정하려면 '선택 확정' 버튼을 눌러줘.",
            ephemeral=True
        )


class EphemeralCaptainBanView(discord.ui.View):
    """View with button for current captain to open their private ban interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        
        # Add ban button only for the current banning captain
        if draft.current_banning_captain:
            captain_name = draft.players[draft.current_banning_captain].username
            button = OpenCaptainBanInterfaceButton(draft.current_banning_captain, captain_name)
            self.add_item(button)


class OpenCaptainBanInterfaceButton(discord.ui.Button):
    """Button for the current captain to open their private ban interface"""
    
    def __init__(self, captain_id: int, captain_name: str):
        super().__init__(
            label=f"{captain_name} - 밴 선택 (1개)",
            style=discord.ButtonStyle.danger,
            custom_id=f"open_captain_ban_{captain_id}",
            emoji="🚫"
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private ban interface for the current captain"""
        user_id = interaction.user.id
        view: EphemeralCaptainBanView = self.view
        
        # CRITICAL: Check if draft phase has moved beyond banning
        if view.draft.phase != DraftPhase.SERVANT_BAN:
            await interaction.response.send_message(
                "밴 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # Check if it's the current captain's turn
        if view.draft.current_banning_captain != self.captain_id:
            await interaction.response.send_message(
                "지금은 네 차례가 아니야. 순서를 기다려줘.", ephemeral=True
            )
            return
        
        # CRITICAL: Additional check - if captain already completed their ban AND it's no longer their turn
        if (view.draft.captain_ban_progress.get(self.captain_id, False) and 
            view.draft.current_banning_captain != self.captain_id):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            ban_text = current_bans[0] if current_bans else "없음"
            await interaction.response.send_message(
                f"이미 밴을 완료했어: **{ban_text}**\n"
                "완료된 밴은 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # In test mode, allow the real user to access any captain's interface
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            pass
        elif user_id != self.captain_id:
            await interaction.response.send_message(
                "자신의 밴 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        

        
        # Check if already completed
        if view.draft.captain_ban_progress.get(self.captain_id, False):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            if current_bans:
                ban_text = current_bans[0]
                # Ban completed and recorded - no editing allowed
                await interaction.response.send_message(
                    f"이미 밴을 완료했어: **{ban_text}**\n"
                    "확정된 밴은 변경할 수 없어.", 
                    ephemeral=True
                )
            else:
                # No bans recorded but marked complete - allow them to select
                await interaction.response.send_message(
                    "밴을 완료했지만 선택이 없어. 다시 선택해줘.", 
                    ephemeral=True,
                    view=PrivateCaptainBanView(view.draft, view.bot_commands, self.captain_id)
                )
            return
        
        # Open private ban interface
        await interaction.response.send_message(
            "🚫 **개인 밴 인터페이스**\n"
            "밴하고 싶은 서번트를 **1명** 선택해줘.\n"
            "상대방은 네 선택을 볼 수 없어.",
            ephemeral=True,
            view=PrivateCaptainBanView(view.draft, view.bot_commands, self.captain_id)
        )


class PrivateCaptainBanView(discord.ui.View):
    """Private ban interface for individual captains in sequential system"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', captain_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.captain_id = captain_id
        self.current_category = "세이버"
        self.selected_ban = None
        
        # If editing existing ban, load it
        existing_bans = draft.captain_bans.get(captain_id, [])
        if existing_bans:
            self.selected_ban = existing_bans[0]
        
        self._add_category_buttons()
        self._add_character_dropdown()
        self._add_confirmation_button()
    
    async def on_timeout(self) -> None:
        """Handle interface timeout - add reopen button to public message"""
        try:
            # Only add reopen functionality if captain hasn't completed their ban yet
            if not self.draft.captain_ban_progress.get(self.captain_id, False):
                await self.bot_commands._add_reopen_captain_ban_interface_button(self.draft, self.captain_id)
        except Exception as e:
            logger.error(f"Error handling captain ban interface timeout: {e}")

    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):
            button = PrivateCaptainBanCategoryButton(category, i)
            self.add_item(button)

    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, PrivateCaptainBanCharacterDropdown):
                self.remove_item(item)
        
        # Get characters for current category (excluding already banned servants)
        available_in_category = [
            char for char in self.draft.servant_categories[self.current_category]
            if char not in self.draft.banned_servants
        ]
        
        if available_in_category:
            dropdown = PrivateCaptainBanCharacterDropdown(
                self.draft, self.bot_commands, available_in_category, 
                self.current_category, self.captain_id
            )
            self.add_item(dropdown)

    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmCaptainBanButton(self.captain_id)
        self.add_item(button)

    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        ban_text = f"현재 선택: {self.selected_ban if self.selected_ban else '없음'}"
        
        embed = discord.Embed(
            title=f"🚫 밴 선택 - {new_category}",
            description=f"**현재 카테고리: {new_category}**\n{ban_text}",
            color=INFO_COLOR
        )
        
        # Show characters in current category
        chars_in_category = self.draft.servant_categories[new_category]
        char_list = "\n".join([
            f"{'❌' if char in self.draft.banned_servants else '•'} {char}" 
            for char in chars_in_category
        ])
        embed.add_field(name=f"{new_category} 서번트 목록", value=char_list, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


class PrivateCaptainBanCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private captain ban interface"""
    
    def __init__(self, category: str, index: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_captain_ban_category_{category}",
            row=index // 4  # Distribute across rows
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        view: PrivateCaptainBanView = self.view
        
        # CRITICAL: Check if draft phase has moved beyond banning
        if view.draft.phase != DraftPhase.SERVANT_BAN:
            await interaction.response.send_message(
                "밴 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # CRITICAL: Additional check - if captain already completed their ban AND it's no longer their turn
        if (view.draft.captain_ban_progress.get(view.captain_id, False) and 
            view.draft.current_banning_captain != view.captain_id):
            current_bans = view.draft.captain_bans.get(view.captain_id, [])
            ban_text = current_bans[0] if current_bans else "없음"
            await interaction.response.send_message(
                f"이미 밴을 완료했어: **{ban_text}**\n"
                "완료된 밴은 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # Validate user is the captain (with test mode support)
        if view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id:
            # In test mode, allow the real user to access any captain's interface
            pass
        elif interaction.user.id != view.captain_id:
            await interaction.response.send_message(
                "이 인터페이스는 네가 사용할 수 없어.", ephemeral=True
            )
            return
        
        await view.update_category(self.category, interaction)


class PrivateCaptainBanCharacterDropdown(discord.ui.Select):
    """Dropdown for selecting characters to ban in private captain interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', characters: List[str], category: str, captain_id: int):
        self.draft = draft
        self.bot_commands = bot_commands
        self.category = category
        self.captain_id = captain_id
        
        # Get current ban selection
        current_bans = draft.captain_bans.get(captain_id, [])
        current_ban = current_bans[0] if current_bans else None
        
        options = [
            discord.SelectOption(
                label=char, 
                value=char, 
                description=f"{category} 클래스",
                default=char == current_ban
            )
            for char in characters[:25]
        ]
        
        super().__init__(
            placeholder=f"{category} 서번트 밴 선택...",
            options=options,
            min_values=1,
            max_values=1,
            row=3
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle character ban selection"""
        view: PrivateCaptainBanView = self.view
        
        # CRITICAL: Check if draft phase has moved beyond banning
        if view.draft.phase != DraftPhase.SERVANT_BAN:
            await interaction.response.send_message(
                "밴 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # CRITICAL: Additional check - if captain already completed their ban AND it's no longer their turn
        if (view.draft.captain_ban_progress.get(self.captain_id, False) and 
            view.draft.current_banning_captain != self.captain_id):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            ban_text = current_bans[0] if current_bans else "없음"
            await interaction.response.send_message(
                f"이미 밴을 완료했어: **{ban_text}**\n"
                "완료된 밴은 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # Validate user is the captain (with test mode support)
        if view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id:
            # In test mode, allow the real user to access any captain's interface
            pass
        elif interaction.user.id != self.captain_id:
            await interaction.response.send_message(
                "이 인터페이스는 네가 사용할 수 없어.", ephemeral=True
            )
            return
        
        # Update selected ban
        view.selected_ban = self.values[0]
        
        await interaction.response.send_message(
            f"**{self.values[0]}** ({self.category})을(를) 밴으로 선택했어!\n"
            "확정하려면 '밴 확정' 버튼을 눌러줘.",
            ephemeral=True
        )


class ConfirmCaptainBanButton(discord.ui.Button):
    """Button to confirm captain ban selection"""
    
    def __init__(self, captain_id: int):
        super().__init__(
            label="밴 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_captain_ban_{captain_id}",
            emoji="✅",
            row=4
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Confirm captain ban selection"""
        view: PrivateCaptainBanView = self.view
        
        # CRITICAL: Check if draft phase has moved beyond banning
        if view.draft.phase != DraftPhase.SERVANT_BAN:
            await interaction.response.send_message(
                "밴 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # CRITICAL: Additional check - if captain already completed their ban AND it's no longer their turn
        if (view.draft.captain_ban_progress.get(self.captain_id, False) and 
            view.draft.current_banning_captain != self.captain_id):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            ban_text = current_bans[0] if current_bans else "없음"
            await interaction.response.send_message(
                f"이미 밴을 완료했어: **{ban_text}**\n"
                "완료된 밴은 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # Validate user is the captain (with test mode support)
        if view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id:
            # In test mode, allow the real user to access any captain's interface
            pass
        elif interaction.user.id != self.captain_id:
            await interaction.response.send_message(
                "이 인터페이스는 네가 사용할 수 없어.", ephemeral=True
            )
            return
        
        if not view.selected_ban:
            await interaction.response.send_message(
                "밴할 서번트를 선택해줘.",
                ephemeral=True
            )
            return
        
        # Save ban
        view.draft.captain_bans[self.captain_id] = [view.selected_ban]
        view.draft.captain_ban_progress[self.captain_id] = True
        
        # Immediately add the ban to banned_servants to prevent other captains from selecting it
        view.draft.banned_servants.add(view.selected_ban)
        
        # Note: With new simple ID verification, no session invalidation needed
        
        captain_name = view.draft.players[self.captain_id].username
        
        await interaction.response.send_message(
            f"✅ **밴 완료!**\n"
            f"**{captain_name}**이(가) **{view.selected_ban}**을(를) 밴했어.",
            ephemeral=True
        )
        
        # Advance to next captain's turn or complete bans
        await view.bot_commands._advance_captain_ban_turn(view.draft)


class ConfirmTeamSelectionButton(discord.ui.Button):
    """Button to confirm team selection choices"""
    
    def __init__(self, captain_id: int):
        super().__init__(
            label="선택 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_team_selection_{captain_id}",
            emoji="✅"
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Confirm team selection and assign players to teams"""
        view: TeamSelectionView = self.view
        user_id = interaction.user.id
        
        # Validate current phase
        if view.draft.phase != DraftPhase.TEAM_SELECTION:
            await interaction.response.send_message(
                "팀 선택 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
        # Validate captain permission
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            # In test mode, real user can confirm for any captain
            pass
        elif user_id != self.captain_id:
            await interaction.response.send_message(
                "자신의 선택만 확정할 수 있어.", ephemeral=True
            )
            return
        
        # Validate it's the captain's turn
        if view.draft.current_picking_captain != self.captain_id:
            await interaction.response.send_message(
                "지금은 네 차례가 아니야.", ephemeral=True
            )
            return
        
        # CRITICAL: Check if captain already completed their selections for this round
        current_round = view.draft.team_selection_round
        if (self.captain_id in view.draft.team_selection_progress and 
            current_round in view.draft.team_selection_progress[self.captain_id] and
            view.draft.team_selection_progress[self.captain_id][current_round]):
            await interaction.response.send_message(
                "이번 라운드 선택을 이미 완료했어. 더 이상 변경할 수 없어.", ephemeral=True
            )
            return
        
        # Get pending selections
        pending_selections = view.draft.pending_team_selections.get(self.captain_id, [])
        if not pending_selections:
            await interaction.response.send_message(
                "선택할 플레이어를 먼저 골라줘.", ephemeral=True
            )
            return
        
        # Validate pick count for this round
        round_info = view.bot_commands.team_selection_patterns[view.draft.team_size][view.draft.team_selection_round - 1]
        is_first_pick = self.captain_id == view.draft.first_pick_captain
        max_picks = round_info["first_pick"] if is_first_pick else round_info["second_pick"]
        
        if len(pending_selections) != max_picks:
            await interaction.response.send_message(
                f"이번 라운드에서는 정확히 {max_picks}명을 선택해야 해. (현재: {len(pending_selections)}명)", 
                ephemeral=True
            )
            return
        
        # Confirm the selections - assign players to teams
        captain_team = view.draft.players[self.captain_id].team
        confirmed_names = []
        
        for player_id in pending_selections:
            view.draft.players[player_id].team = captain_team
            confirmed_names.append(view.draft.players[player_id].username)
        
        # Update pick count
        view.draft.picks_this_round[self.captain_id] += len(pending_selections)
        
        # Mark round as completed for this captain
        if self.captain_id not in view.draft.team_selection_progress:
            view.draft.team_selection_progress[self.captain_id] = {}
        view.draft.team_selection_progress[self.captain_id][current_round] = True
        
        # Clear pending selections
        view.draft.pending_team_selections[self.captain_id] = []
        
        await interaction.response.send_message(
            f"✅ **팀 선택 확정!**\n"
            f"팀 {captain_team}에 추가: {', '.join(confirmed_names)}", 
            ephemeral=False
        )
        
        # Send confirmation update to main channel as well
        try:
            main_channel = view.bot_commands.bot.get_channel(view.draft.channel_id) if view.bot_commands.bot else None
            if main_channel and view.draft.thread_id:  # Only if in hybrid mode
                captain_name = view.draft.players[self.captain_id].username
                main_embed = discord.Embed(
                    title="✅ 팀 선택 확정",
                    description=f"**{captain_name}** (팀 {captain_team})이(가) 선택을 확정했어!",
                    color=SUCCESS_COLOR
                )
                main_embed.add_field(
                    name="추가된 플레이어",
                    value="\n".join([f"• {name}" for name in confirmed_names]),
                    inline=False
                )
                
                await view.bot_commands._safe_api_call(
                    lambda: main_channel.send(embed=main_embed),
                    bucket=f"team_confirm_main_{view.draft.channel_id}"
                )
        except Exception as e:
            logger.warning(f"Failed to send team confirmation to main channel: {e}")
        
        # Auto-complete remaining picks in test mode
        if view.draft.is_test_mode:
            await self._auto_complete_test_team_selection(view.draft, view.bot_commands)
        
        # Continue team selection
        await view.bot_commands._continue_team_selection_for_draft(view.draft)
    
    async def _auto_complete_test_team_selection(self, draft: DraftSession, bot_commands: 'TeamDraftCommands') -> None:
        """Auto-complete team selection in test mode"""
        
        # Get all unassigned players (excluding captains)
        unassigned_players = [
            player for player in draft.players.values()
            if player.team is None and not player.is_captain
        ]
        
        # Assign remaining players randomly to teams while respecting team size limits
        team1_count = sum(1 for p in draft.players.values() if p.team == 1)
        team2_count = sum(1 for p in draft.players.values() if p.team == 2)
        target_team_size = draft.team_size
        
        for player in unassigned_players:
            # Assign to team with fewer members, or randomly if equal
            if team1_count < target_team_size and (team2_count >= target_team_size or random.choice([True, False])):
                player.team = 1
                team1_count += 1
            elif team2_count < target_team_size:
                player.team = 2
                team2_count += 1