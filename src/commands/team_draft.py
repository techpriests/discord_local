import logging
import random
import asyncio
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple, Union
from enum import Enum
from dataclasses import dataclass, field
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.decorators import command_handler
from .base_commands import BaseCommands
from src.utils.types import CommandContext
from src.utils.constants import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR

logger = logging.getLogger(__name__)


class DraftPhase(Enum):
    """Phases of the draft system"""
    WAITING = "waiting"
    CAPTAIN_VOTING = "captain_voting"
    SERVANT_BAN = "servant_ban"
    SERVANT_SELECTION = "servant_selection"
    SERVANT_RESELECTION = "servant_reselection"
    TEAM_SELECTION = "team_selection"
    FINAL_SWAP = "final_swap"
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
    team_size: int = 6  # Number of players per team (3 for 3v3, 6 for 6v6)
    phase: DraftPhase = DraftPhase.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    
    # Test mode tracking
    is_test_mode: bool = False
    real_user_id: Optional[int] = None  # The real user in test mode
    
    # Captain selection
    captain_vote_message_id: Optional[int] = None
    captains: List[int] = field(default_factory=list)  # user_ids
    
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
    conflicted_servants: Dict[str, List[int]] = field(default_factory=dict)
    confirmed_servants: Dict[int, str] = field(default_factory=dict)
    
    # Team selection
    first_pick_captain: Optional[int] = None
    team_selection_round: int = 1
    current_picking_captain: Optional[int] = None
    picks_this_round: Dict[int, int] = field(default_factory=dict)  # captain_id -> picks_made
    
    # Servant ban phase
    banned_servants: Set[str] = field(default_factory=set)
    captain_bans: Dict[int, List[str]] = field(default_factory=dict)  # captain_id -> banned_servants
    captain_ban_progress: Dict[int, bool] = field(default_factory=dict)  # captain_id -> completed
    
    # Servant selection progress tracking
    selection_progress: Dict[int, bool] = field(default_factory=dict)  # player_id -> completed
    
    # Interface session management (replacement system)
    ban_interface_sessions: Dict[int, str] = field(default_factory=dict)  # captain_id -> session_id
    selection_interface_sessions: Dict[int, str] = field(default_factory=dict)  # player_id -> session_id
    
    # Messages for state tracking
    status_message_id: Optional[int] = None
    ban_progress_message_id: Optional[int] = None
    selection_progress_message_id: Optional[int] = None


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
        
        # Start cleanup task
        if bot:
            bot.loop.create_task(self._cleanup_task())
        
        # Rate limiting for Discord API calls
        self.rate_limit_buckets: Dict[str, float] = {}  # bucket -> last_call_time
        self.api_call_counts: Dict[str, int] = {}  # bucket -> call_count
        
        # Selection patterns for team picking
        self.team_selection_patterns = {
            6: [  # 6v6 pattern (original)
                {"first_pick": 1, "second_pick": 2},  # Round 1
                {"first_pick": 2, "second_pick": 2},  # Round 2
                {"first_pick": 1, "second_pick": 1},  # Round 3
                {"first_pick": 1, "second_pick": 0},  # Round 4
            ],
            3: [  # 3v3 pattern (corrected)
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 1, "second_pick": 0},  # Round 2: First picks 1, Second picks 0
            ]
        }

    async def _safe_api_call(self, call_func, bucket: str = "default", max_retries: int = 3):
        """Safely make Discord API calls with rate limiting and retry logic"""
        import asyncio
        
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

    def _generate_session_id(self) -> str:
        """Generate a unique session ID for interface tracking"""
        return str(uuid.uuid4())[:8]  # Short UUID for easier debugging



    async def _add_reopen_ban_interface_button(self, draft: DraftSession, captain_id: int) -> None:
        """Add reopen interface button to ban progress message"""
        try:
            if draft.ban_progress_message_id:
                channel = self.bot.get_channel(draft.channel_id)
                if channel:
                    message = await channel.fetch_message(draft.ban_progress_message_id)
                    if message:
                        # Create a view with just the reopen button for this captain
                        view = ReopenBanInterfaceView(draft, self, captain_id)
                        await message.edit(view=view)
        except Exception as e:
            logger.error(f"Error adding reopen ban interface button: {e}")

    async def _add_reopen_selection_interface_button(self, draft: DraftSession, player_id: int) -> None:
        """Add reopen interface button to selection progress message"""
        try:
            if draft.selection_progress_message_id:
                channel = self.bot.get_channel(draft.channel_id)
                if channel:
                    message = await channel.fetch_message(draft.selection_progress_message_id)
                    if message:
                        # Create a view with just the reopen button for this player
                        view = ReopenSelectionInterfaceView(draft, self, player_id)
                        await message.edit(view=view)
        except Exception as e:
            logger.error(f"Error adding reopen selection interface button: {e}")

    @commands.command(
        name="페어",
        help="팀 드래프트를 시작해 (기본: 6v6, 옵션: 3v3)",
        brief="팀 드래프트 시작",
        aliases=["draft", "팀드래프트"],
        description="팀 드래프트 시스템을 시작해.\n"
                   "사용법: 뮤 페어 [team_size:3]\n"
                   "예시: 뮤 페어 team_size:3 (3v3 드래프트)\n"
                   "예시: 뮤 페어 (6v6 드래프트)"
    )
    async def draft_start_chat(self, ctx: commands.Context, *, args: str = "") -> None:
        """Start team draft via chat command"""
        # Parse test_mode and team_size from args
        test_mode = "test_mode:true" in args.lower() or "test_mode=true" in args.lower()
        
        # Parse team_size (default 6 for 6v6)
        team_size = 6  # default
        if "team_size:3" in args.lower() or "team_size=3" in args.lower():
            team_size = 3
        elif "team_size:6" in args.lower() or "team_size=6" in args.lower():
            team_size = 6
            
        # Pass the args to handle player mentions
        await self._handle_draft_start(ctx, args, test_mode, team_size)

    @app_commands.command(name="페어", description="팀 드래프트를 시작해 (기본: 6v6)")
    async def draft_start_slash(
        self,
        interaction: discord.Interaction,
        players: str = "",
        test_mode: bool = False,
        team_size: int = 6
    ) -> None:
        """Start a new draft session"""
        # Validate team_size
        if team_size not in [3, 6]:
            await interaction.response.send_message(
                "팀 크기는 3 (3v3) 또는 6 (6v6)만 가능해.", ephemeral=True
            )
            return
            
        logger.info(f"페어 command called by {interaction.user.name} with test_mode={test_mode}, team_size={team_size} (v4)")
        try:
            await self._handle_draft_start(interaction, players, test_mode, team_size)
        except Exception as e:
            logger.error(f"Error in draft_start_slash: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⚠️ 명령어 실행 중 문제가 생겼어: {str(e)}", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ 명령어 실행 중 문제가 생겼어: {str(e)}", 
                    ephemeral=True
                )

    @command_handler()
    async def _handle_draft_start(
        self,
        ctx_or_interaction: CommandContext,
        players_str: str = "",
        test_mode: bool = False,
        team_size: int = 6
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
                team_format = "3v3" if team_size == 3 else "6v6"
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
                    await self.send_error(
                        ctx_or_interaction, 
                        f"정확히 {total_players_needed}명의 플레이어가 필요해. (현재: {len(players)}명)\n"
                        #"💡 **팁**: 테스트 모드를 사용해볼래?"
                    )
                    return
            
            # Create draft session
            draft = DraftSession(channel_id=channel_id, guild_id=guild_id, team_size=team_size)
            
            # Set test mode flag and real user if in test mode
            if test_mode:
                draft.is_test_mode = True
                draft.real_user_id = self.get_user_id(ctx_or_interaction)
            
            for user_id, username in players:
                sanitized_username = self._sanitize_username(username)
                draft.players[user_id] = Player(user_id=user_id, username=sanitized_username)
            
            self.active_drafts[channel_id] = draft
            self.draft_start_times[channel_id] = time.time()  # Record start time
            
            # Start captain voting
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
        import random
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

    async def _start_captain_voting(
        self,
        ctx_or_interaction: CommandContext,
        draft: DraftSession
    ) -> None:
        """Start the captain voting phase"""
        draft.phase = DraftPhase.CAPTAIN_VOTING
        
        embed = discord.Embed(
            title="🎖️ 팀장 선출 투표",
            description="모든 플레이어는 팀장으로 추천하고 싶은 2명에게 투표해.\n"
                       "가장 많은 표를 받은 2명이 팀장이 돼.",
            color=INFO_COLOR
        )
        
        player_list = "\n".join([f"{i+1}. {player.username}" 
                                for i, player in enumerate(draft.players.values())])
        embed.add_field(name="참가자 목록", value=player_list, inline=False)
        embed.add_field(name="투표 방법", value="아래 번호 버튼을 눌러 투표해", inline=False)
        
        # Create voting view
        view = CaptainVotingView(draft, self)
        
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
        team_format = "3v3" if draft.team_size == 3 else "6v6"
        embed = discord.Embed(title=f"🏆 드래프트 현황 ({team_format})", color=INFO_COLOR)
        
        phase_names = {
            DraftPhase.WAITING: "대기 중",
            DraftPhase.CAPTAIN_VOTING: "팀장 선출 투표",
            DraftPhase.SERVANT_BAN: "서번트 밴",
            DraftPhase.SERVANT_SELECTION: "서번트 선택",
            DraftPhase.SERVANT_RESELECTION: "서번트 재선택",
            DraftPhase.TEAM_SELECTION: "팀원 선택",
            DraftPhase.FINAL_SWAP: "최종 교체",
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
            "✅ **팀 드래프트 시스템이 작동해!** (v4.0)\n\n"
            "사용법:\n"
            "• `/페어 team_size:3` - 3v3 드래프트 시작 (6명 필요)\n"
            "• `/페어` - 6v6 드래프트 시작 (12명 필요)\n"
            "• `/페어상태` - 현재 드래프트 상태 확인\n\n",
            ephemeral=True
        )

    async def _start_servant_selection(self, draft: DraftSession = None) -> None:
        """Start servant selection phase using ephemeral interfaces"""
        # Use provided draft or find the current one
        if draft:
            current_draft = draft
            channel = self.bot.get_channel(draft.channel_id)
        else:
            # Find the channel and draft (fallback for legacy calls)
            channel = None
            current_draft = None
            for channel_id, d in self.active_drafts.items():
                if d.phase == DraftPhase.SERVANT_SELECTION:
                    try:
                        channel = self.bot.get_channel(channel_id)
                        current_draft = d
                        break
                    except Exception as e:
                        logger.error(f"Error getting channel {channel_id}: {e}")
                        continue
        
        if not channel or not current_draft:
            logger.warning(f"Could not find channel or draft. channel: {channel}, current_draft: {current_draft}")
            return
        
        # Remove banned servants from available list
        current_draft.available_servants = current_draft.available_servants - current_draft.banned_servants
        
        # Initialize selection progress tracking
        for player_id in current_draft.players.keys():
            current_draft.selection_progress[player_id] = False
        
        # Send public progress embed
        embed = discord.Embed(
            title="⚔️ 서번트 선택 단계",
            description="모든 플레이어가 개별적으로 서번트를 선택 중이야.\n"
                       "**👇 자신의 닉네임 버튼을 눌러서 서번트를 선택해!**\n"
                       "선택 내용은 모든 플레이어가 완료된 후에 공개될거야.",
            color=INFO_COLOR
        )
        
        # Show banned servants summary
        if current_draft.banned_servants:
            banned_list = ", ".join(sorted(current_draft.banned_servants))
            embed.add_field(name="🚫 밴된 서번트", value=banned_list, inline=False)
        
        # Add progress status
        await self._update_selection_progress_embed(current_draft, embed)
        
        # Send public message and create ephemeral selection buttons
        view = EphemeralSelectionView(current_draft, self)
        try:
            message = await self._safe_api_call(
                lambda: channel.send(embed=embed, view=view), 
                bucket=f"selection_{current_draft.channel_id}"
            )
            current_draft.selection_progress_message_id = message.id
        except Exception as e:
            logger.error(f"Failed to send servant selection message: {e}")
            # Try to send a simplified message without view
            try:
                await self._safe_api_call(
                    lambda: channel.send(embed=embed),
                    bucket=f"selection_fallback_{current_draft.channel_id}"
                )
            except Exception as fallback_error:
                logger.error(f"Failed to send fallback selection message: {fallback_error}")
                raise

    async def _update_selection_progress_embed(self, draft: DraftSession, embed: discord.Embed) -> None:
        """Update selection progress in the embed"""
        progress_text = ""
        completed_count = 0
        
        for player_id, player in draft.players.items():
            status = "✅ 완료" if draft.selection_progress.get(player_id, False) else "⏳ 진행 중"
            progress_text += f"{player.username}: {status}\n"
            if draft.selection_progress.get(player_id, False):
                completed_count += 1
        
        total_players = len(draft.players)
        embed.add_field(
            name=f"진행 상황 ({completed_count}/{total_players})",
            value=progress_text.strip(),
            inline=False
        )

    async def _update_selection_progress_message(self, draft: DraftSession) -> None:
        """Update the public selection progress message"""
        if not draft.selection_progress_message_id:
            return
            
        channel = self.bot.get_channel(draft.channel_id)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(draft.selection_progress_message_id)
            embed = discord.Embed(
                title="⚔️ 서번트 선택 단계",
                description="모든 플레이어가 개별적으로 서번트를 선택 중이야.\n"
                           "**👇 자신의 닉네임 버튼을 눌러서 서번트를 선택해!**\n"
                           "선택 내용은 모든 플레이어가 완료된 후에 공개될거야.",
                color=INFO_COLOR
            )
            
            # Show banned servants summary
            if draft.banned_servants:
                banned_list = ", ".join(sorted(draft.banned_servants))
                embed.add_field(name="🚫 밴된 서번트", value=banned_list, inline=False)
            
            await self._update_selection_progress_embed(draft, embed)
            
            # Keep the same view if not all players are done
            if not all(draft.selection_progress.values()):
                view = EphemeralSelectionView(draft, self)
                await message.edit(embed=embed, view=view)
            else:
                await message.edit(embed=embed, view=None)
        except discord.NotFound:
            logger.warning("Selection progress message not found")

    async def _auto_complete_test_selections(self, draft: DraftSession) -> None:
        """Auto-complete servant selections for test mode fake players"""
        import random
        
        # Get available servants (exclude banned and already selected)
        taken_servants = {p.selected_servant for p in draft.players.values() if p.selected_servant}
        available_servants = list(draft.available_servants - draft.banned_servants - taken_servants)
        
        # Auto-select for players who haven't selected yet
        for player_id, player in draft.players.items():
            if not player.selected_servant and player_id != draft.real_user_id:  # Fake player
                if available_servants:
                    servant = random.choice(available_servants)
                    player.selected_servant = servant
                    draft.selection_progress[player_id] = True
                    available_servants.remove(servant)
                    logger.info(f"Auto-selected {servant} for fake player {player.username}")

    async def _reveal_servant_selections(self, draft: DraftSession = None) -> None:
        """Reveal servant selections and handle conflicts"""
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
        
        channel = self.bot.get_channel(current_channel_id)
        if not channel:
            return
        
        if conflicts:
            # Handle conflicts with dice rolls
            embed = discord.Embed(
                title="🎲 서번트 선택 결과 - 중복이 있어.",
                description="중복 선택된 서번트가 있네. 주사위로 결정하자.",
                color=ERROR_COLOR
            )
            
            for servant, user_ids in conflicts.items():
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
                
                # Set winner and reset losers
                current_draft.confirmed_servants[winner_id] = servant
                original_losers = [uid for uid in user_ids if uid != winner_id]
                current_draft.conflicted_servants[servant] = original_losers
                
                # Reset all original conflicted users except winner
                for user_id in conflicts[servant]:  # Use original conflict list
                    if user_id != winner_id:
                        current_draft.players[user_id].selected_servant = None
                
                # Add to embed with tie information
                roll_text = "\n".join([
                    f"{current_draft.players[uid].username}: {rolls[uid]} {'✅' if uid == winner_id else '❌'}"
                    for uid in conflicts[servant]  # Show all original players
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
                await self._start_team_selection(current_draft, current_channel_id)
        else:
            # No conflicts, confirm all
            for user_id, player in current_draft.players.items():
                current_draft.confirmed_servants[user_id] = player.selected_servant
            
            embed = discord.Embed(
                title="✅ 서번트 선택 완료",
                description="모든 플레이어의 서번트 선택이 완료됐어.",
                color=SUCCESS_COLOR
            )
            
            # Show all selections grouped by category
            for category, characters in current_draft.servant_categories.items():
                selected_in_category = []
                for player in current_draft.players.values():
                    if player.selected_servant in characters:
                        selected_in_category.append(f"{player.username}: {player.selected_servant}")
                
                if selected_in_category:
                    embed.add_field(
                        name=f"{category} 클래스",
                        value="\n".join(selected_in_category),
                        inline=True
                    )
            
            await self._safe_api_call(
                lambda: channel.send(embed=embed),
                bucket=f"reveal_{current_draft.channel_id}"
            )
            await self._start_team_selection(current_draft, current_channel_id)

    async def _start_servant_reselection(self, draft: DraftSession, channel_id: int) -> None:
        """Start servant reselection for conflict losers"""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        
        # Get users who need to reselect
        reselect_users = []
        for servant, user_ids in draft.conflicted_servants.items():
            reselect_users.extend(user_ids)
        
        # Remove taken servants from available list
        taken_servants = set(draft.confirmed_servants.values())
        draft.available_servants = draft.available_servants - taken_servants - draft.banned_servants
        
        embed = discord.Embed(
            title="🔄 서번트 재선택",
            description="중복으로 인해 서번트를 다시 선택해야 하는 플레이어들이 있어.\n"
                       "**현재 카테고리: 세이버**\n"
                       "❌ 표시된 서번트는 이미 선택되었거나 금지되어 선택할 수 없어.",
            color=INFO_COLOR
        )
        
        reselect_names = [draft.players[uid].username for uid in reselect_users]
        embed.add_field(name="재선택 대상", value="\n".join(reselect_names), inline=False)
        
        # Show available characters in first category
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
                  "❌ 표시된 서번트는 이미 선택되어 있어.",
            inline=False
        )
        
        # Create ephemeral selection interface for reselection
        # Only show buttons for users who need to reselect
        view = EphemeralSelectionView(draft, self)
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"reselection_{channel_id}"
        )

    async def _start_team_selection(self, draft: DraftSession, channel_id: int) -> None:
        """Start team selection phase"""
        draft.phase = DraftPhase.TEAM_SELECTION
        
        # Roll dice to determine first pick
        captain1, captain2 = draft.captains
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
        
        # Assign captains to teams
        draft.players[captain1].team = 1
        draft.players[captain2].team = 2
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
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
        await self._continue_team_selection_for_draft(draft)

    async def _continue_team_selection_for_draft(self, draft: DraftSession) -> None:
        """Continue team selection process for a specific draft"""
        # Check if team selection is complete
        total_players = draft.team_size * 2
        assigned_players = sum(1 for p in draft.players.values() if p.team is not None)
        if assigned_players == total_players:
            await self._start_final_swap_phase_for_draft(draft)
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
                draft.current_picking_captain = draft.first_pick_captain
        
        # Show current picking status and available players
        await self._show_team_selection_status_for_draft(draft)

    async def _show_team_selection_status_for_draft(self, draft: DraftSession) -> None:
        """Show current team selection status for a specific draft"""
        # Find the channel
        channel = None
        for channel_id, d in self.active_drafts.items():
            if d == draft:
                channel = self.bot.get_channel(channel_id)
                break
        
        if not channel:
            return
        
        current_captain = draft.current_picking_captain
        round_info = self.team_selection_patterns[draft.team_size][draft.team_selection_round - 1]
        
        embed = discord.Embed(
            title=f"👥 팀 선택 - 라운드 {draft.team_selection_round}",
            description=f"현재 {draft.players[current_captain].username}의 차례야.",
            color=INFO_COLOR
        )
        
        # Show available players
        available_players = [
            p for p in draft.players.values() 
            if p.team is None and not p.is_captain
        ]
        
        if available_players:
            available_list = "\n".join([
                f"{i+1}. {p.username} ({draft.confirmed_servants[p.user_id]})"
                for i, p in enumerate(available_players)
            ])
            embed.add_field(name="선택 가능한 플레이어", value=available_list, inline=False)
        
        # Show current teams
        team1_players = [p for p in draft.players.values() if p.team == 1]
        team2_players = [p for p in draft.players.values() if p.team == 2]
        
        team1_text = "\n".join([f"{p.username} ({draft.confirmed_servants[p.user_id]})" for p in team1_players])
        team2_text = "\n".join([f"{p.username} ({draft.confirmed_servants[p.user_id]})" for p in team2_players])
        
        embed.add_field(name="팀 1", value=team1_text or "없음", inline=True)
        embed.add_field(name="팀 2", value=team2_text or "없음", inline=True)
        
        # Create selection view
        view = TeamSelectionView(draft, self, available_players)
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"team_selection_status_{draft.channel_id}"
        )

    @command_handler()
    async def _handle_draft_cancel(self, ctx_or_interaction: CommandContext) -> None:
        """Handle draft cancellation"""
        channel_id = self.get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_drafts:
            await self.send_error(ctx_or_interaction, "진행 중인 드래프트가 없어.")
            return
        
        # Clean up session dictionaries to prevent memory leaks
        draft = self.active_drafts[channel_id]
        draft.ban_interface_sessions.clear()
        draft.selection_interface_sessions.clear()
        
        del self.active_drafts[channel_id]
        if channel_id in self.draft_start_times:
            del self.draft_start_times[channel_id]
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

    async def _cleanup_task(self) -> None:
        """Background task to clean up old drafts after 1 hour"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                current_time = time.time()
                expired_channels = []
                
                for channel_id, start_time in self.draft_start_times.items():
                    # Add 30-second safety buffer to prevent cleanup of very fresh drafts during edge cases
                    if current_time - start_time > 3630:  # 1 hour + 30 seconds = 3630 seconds
                        # Additional safety check: ensure draft exists and isn't in early stages
                        draft = self.active_drafts.get(channel_id)
                        if draft:
                            # Don't cleanup drafts in captain voting phase (early stage)
                            if draft.phase != DraftPhase.CAPTAIN_VOTING:
                                expired_channels.append(channel_id)
                            else:
                                logger.info(f"Skipping cleanup of channel {channel_id} - still in captain voting phase")
                        else:
                            # Orphaned timestamp - safe to clean
                            expired_channels.append(channel_id)
                
                for channel_id in expired_channels:
                    logger.info(f"Auto-cleaning expired draft in channel {channel_id} (safety check passed)")
                    
                    # Clean up draft state
                    if channel_id in self.active_drafts:
                        draft = self.active_drafts[channel_id]
                        # Clean up session dictionaries to prevent memory leaks
                        draft.ban_interface_sessions.clear()
                        draft.selection_interface_sessions.clear()
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
                                    description="1시간이 지나서 드래프트를 자동으로 정리했어.",
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

    async def _start_servant_ban_phase(self, draft: DraftSession) -> None:
        """Start servant ban phase where captains ban 2 servants each using ephemeral interfaces"""
        # Find the channel for this draft
        channel = None
        if self.bot:
            # Try to get channel via bot first
            for channel_id, d in self.active_drafts.items():
                if d == draft:
                    channel = self.bot.get_channel(channel_id)
                    break
        
        if not channel:
            logger.warning("Could not find channel for servant ban phase - bot may not be properly initialized")
            return
        
        # Initialize ban progress tracking
        for captain_id in draft.captains:
            draft.captain_ban_progress[captain_id] = False
        
        # Send public progress embed
        embed = discord.Embed(
            title="🚫 서번트 밴 단계",
            description="각 팀장이 개별적으로 밴할 서번트를 선택 중이야.\n"
                       "밴 내용은 양쪽 모두 완료된 후에 공개될거야.",
            color=INFO_COLOR
        )
        
        captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
        embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
        
        # Add progress status
        await self._update_ban_progress_embed(draft, embed)
        
        # Send public message and create ephemeral ban buttons
        view = EphemeralBanView(draft, self)
        message = await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"ban_{draft.channel_id}"
        )
        draft.ban_progress_message_id = message.id

    async def _update_ban_progress_embed(self, draft: DraftSession, embed: discord.Embed) -> None:
        """Update ban progress in the embed"""
        progress_text = ""
        for captain_id in draft.captains:
            captain_name = draft.players[captain_id].username
            status = "✅ 완료" if draft.captain_ban_progress.get(captain_id, False) else "⏳ 진행 중"
            progress_text += f"{captain_name}: {status}\n"
        
        # Remove existing progress field if it exists
        embed.clear_fields()
        captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
        embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
        embed.add_field(name="진행 상황", value=progress_text.strip(), inline=False)

    async def _update_ban_progress_message(self, draft: DraftSession) -> None:
        """Update the public ban progress message"""
        if not draft.ban_progress_message_id:
            return
            
        channel = self.bot.get_channel(draft.channel_id)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(draft.ban_progress_message_id)
            embed = discord.Embed(
                title="🚫 서번트 밴 단계",
                description="각 팀장이 개별적으로 밴할 서번트를 선택 중이야.\n"
                           "밴 내용은 양쪽 모두 완료된 후에 공개될거야.",
                color=INFO_COLOR
            )
            await self._update_ban_progress_embed(draft, embed)
            
            # Keep the same view if not all captains are done
            if not all(draft.captain_ban_progress.values()):
                view = EphemeralBanView(draft, self)
                await message.edit(embed=embed, view=view)
            else:
                await message.edit(embed=embed, view=None)
        except discord.NotFound:
            logger.warning("Ban progress message not found")

    async def _complete_servant_bans(self, draft: DraftSession) -> None:
        """Complete servant ban phase and reveal banned servants"""
        # Collect all banned servants
        all_bans = []
        for captain_id, bans in draft.captain_bans.items():
            all_bans.extend(bans)
            draft.banned_servants.update(bans)
        
        embed = discord.Embed(
            title="🚫 서번트 밴 결과",
            description="양 팀장의 밴이 끝났어. 다음 서번트들의 선택이 금지되었네.",
            color=ERROR_COLOR
        )
        
        # Show each captain's bans
        for captain_id in draft.captains:
            captain_name = draft.players[captain_id].username
            captain_bans = draft.captain_bans.get(captain_id, [])
            ban_text = ", ".join(captain_bans) if captain_bans else "없음"
            embed.add_field(name=f"{captain_name}의 밴", value=ban_text, inline=True)
        
        # Show total banned servants
        banned_list = ", ".join(sorted(draft.banned_servants))
        embed.add_field(name="총 밴된 서번트", value=banned_list, inline=False)
        
        # Find the channel and send the message directly
        channel = self.bot.get_channel(draft.channel_id)
        if channel:
            await self._safe_api_call(
                lambda: channel.send(embed=embed),
                bucket=f"ban_results_{draft.channel_id}"
            )
        
        # Move to servant selection phase
        draft.phase = DraftPhase.SERVANT_SELECTION
        await self._start_servant_selection(draft)

    async def _complete_draft(self) -> None:
        """Complete the draft"""
        # Find current draft
        current_draft = None
        current_channel_id = None
        for channel_id, draft in self.active_drafts.items():
            if draft.phase == DraftPhase.FINAL_SWAP:
                current_draft = draft
                current_channel_id = channel_id
                break
        
        if not current_draft:
            return
            
        current_draft.phase = DraftPhase.COMPLETED
        
        channel = self.bot.get_channel(current_channel_id)
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
                f"**{p.username}** - {current_draft.confirmed_servants[p.user_id]} {'👑' if p.is_captain else ''}"
                for p in players
            ])
        
        embed.add_field(name="팀 1", value=format_final_team(team1_players), inline=True)
        embed.add_field(name="팀 2", value=format_final_team(team2_players), inline=True)
        
        await self._safe_api_call(
            lambda: channel.send(embed=embed),
            bucket=f"draft_complete_{current_channel_id}"
        )
        
        # Clean up
        if current_channel_id in self.active_drafts:
            draft = self.active_drafts[current_channel_id]
            # Clean up session dictionaries to prevent memory leaks
            draft.ban_interface_sessions.clear()
            draft.selection_interface_sessions.clear()
            del self.active_drafts[current_channel_id]
        if current_channel_id in self.draft_start_times:
            del self.draft_start_times[current_channel_id]

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

    async def _start_final_swap_phase_for_draft(self, draft: DraftSession) -> None:
        """Start final swap phase for specific draft"""
        draft.phase = DraftPhase.FINAL_SWAP
        
        # Find the channel
        channel = None
        for channel_id, d in self.active_drafts.items():
            if d == draft:
                channel = self.bot.get_channel(channel_id)
                break
        
        if not channel:
            return
        
        embed = discord.Embed(
            title="🔄 최종 교체 단계",
            description="팀 내에서 서번트를 자유롭게 교체할 수 있어.\n"
                       "교체를 원하지 않으면 완료 버튼을 눌러줘.",
            color=INFO_COLOR
        )
        
        # Show final teams
        team1_players = [p for p in draft.players.values() if p.team == 1]
        team2_players = [p for p in draft.players.values() if p.team == 2]
        
        def format_final_team(players):
            return "\n".join([
                f"{p.username} - {draft.confirmed_servants[p.user_id]}"
                for p in players
            ])
        
        embed.add_field(name="팀 1 최종 로스터", value=format_final_team(team1_players), inline=True)
        embed.add_field(name="팀 2 최종 로스터", value=format_final_team(team2_players), inline=True)
        
        view = FinalSwapView(draft, self)
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"final_swap_{draft.channel_id}"
        )


class TeamSelectionView(discord.ui.View):
    """View for team selection"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', available_players: List[Player]):
        super().__init__(timeout=300.0)
        self.draft = draft
        self.bot_commands = bot_commands
        
        if available_players:
            self.add_item(PlayerDropdown(available_players, draft, bot_commands))


class PlayerDropdown(discord.ui.Select):
    """Dropdown for selecting players"""
    
    def __init__(self, available_players: List[Player], draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        self.draft = draft
        self.bot_commands = bot_commands
        
        options = [
            discord.SelectOption(
                label=f"{player.username}",
                description=f"서번트: {draft.confirmed_servants[player.user_id]}",
                value=str(player.user_id)
            )
            for player in available_players[:25]  # Discord limit
        ]
        
        super().__init__(
            placeholder="팀원 선택...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection"""
        user_id = interaction.user.id
        
        # In test mode, allow the real user to select for both teams
        if self.draft.is_test_mode and user_id == self.draft.real_user_id:
            # Real user can pick for any captain in test mode
            pass
        elif user_id != self.draft.current_picking_captain:
            await interaction.response.send_message(
                "지금은 네 차례가 아니야.", ephemeral=True
            )
            return
        
        selected_player_id = int(self.values[0])
        target_player = self.draft.players[selected_player_id]
        
        # Assign player to team
        current_captain = self.draft.current_picking_captain
        captain_team = self.draft.players[current_captain].team
        target_player.team = captain_team
        
        # Update pick count
        self.draft.picks_this_round[current_captain] += 1
        
        await interaction.response.send_message(
            f"**{target_player.username}**을(를) 팀 {captain_team}에 추가했어!", ephemeral=False
        )
        
        # Auto-complete remaining picks in test mode
        if self.draft.is_test_mode:
            await self._auto_complete_team_selection()
        
        # Continue team selection
        await self.bot_commands._continue_team_selection_for_draft(self.draft)
    
    async def _auto_complete_team_selection(self) -> None:
        """Auto-complete team selection in test mode"""
        import random
        
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


class FinalSwapView(discord.ui.View):
    """View for final swapping phase"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=600.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.team_ready = {1: False, 2: False}
        
        self.add_item(CompleteButton(1))
        self.add_item(CompleteButton(2))


class CompleteButton(discord.ui.Button):
    """Button to complete the draft for a team"""
    
    def __init__(self, team_number: int):
        super().__init__(
            label=f"팀 {team_number} 완료",
            style=discord.ButtonStyle.primary,
            custom_id=f"complete_{team_number}"
        )
        self.team_number = team_number

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle team completion"""
        view: FinalSwapView = self.view
        user_id = interaction.user.id
        
        # Check if user is captain of this team
        player = view.draft.players.get(user_id)
        if not player:
            await interaction.response.send_message(
                "드래프트 참가자가 아니야.", ephemeral=True
            )
            return
            
        user_team = player.team
        is_captain = player.is_captain
        
        # In test mode, allow the real user to complete for any team
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            # In test mode, the real user can act as any captain
            is_captain = True
        
        if not is_captain or user_team != self.team_number:
            await interaction.response.send_message(
                f"팀 {self.team_number}의 팀장만 완료할 수 있어.", ephemeral=True
            )
            return
        
        view.team_ready[self.team_number] = True
        self.disabled = True
        
        await interaction.response.edit_message(view=view)
        
        # Check if both teams are ready
        if all(view.team_ready.values()):
            await view.bot_commands._complete_draft()


class EphemeralBanView(discord.ui.View):
    """View with buttons for captains to open their private ban interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=600.0)
        self.draft = draft
        self.bot_commands = bot_commands
        
        # Add ban button for each captain
        for captain_id in draft.captains:
            captain_name = draft.players[captain_id].username
            button = OpenBanInterfaceButton(captain_id, captain_name)
            self.add_item(button)


class OpenBanInterfaceButton(discord.ui.Button):
    """Button for captains to open their private ban interface"""
    
    def __init__(self, captain_id: int, captain_name: str):
        super().__init__(
            label=f"{captain_name} - 밴 선택",
            style=discord.ButtonStyle.danger,
            custom_id=f"open_ban_{captain_id}",
            emoji="🚫"
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private ban interface for the captain"""
        user_id = interaction.user.id
        view: EphemeralBanView = self.view
        
        # In test mode, allow the real user to access any captain's interface
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            pass
        elif user_id != self.captain_id:
            await interaction.response.send_message(
                "자신의 밴 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        
        # Generate new session ID and invalidate any existing sessions
        session_id = view.bot_commands._generate_session_id()
        view.draft.ban_interface_sessions[self.captain_id] = session_id
        
        # Check if already completed
        if view.draft.captain_ban_progress.get(self.captain_id, False):
            current_bans = view.draft.captain_bans.get(self.captain_id, [])
            if current_bans:
                ban_text = ", ".join(current_bans)
                await interaction.response.send_message(
                    f"이미 밴을 완료했어: **{ban_text}**\n"
                    "변경하려면 다시 선택하고 확정해줘.", 
                    ephemeral=True, 
                    view=PrivateBanView(view.draft, view.bot_commands, self.captain_id, session_id)
                )
            else:
                await interaction.response.send_message(
                    "밴을 완료했지만 선택이 없어. 다시 선택해줘.", 
                    ephemeral=True,
                    view=PrivateBanView(view.draft, view.bot_commands, self.captain_id, session_id)
                )
            return
        
        # Open private ban interface
        await interaction.response.send_message(
            "🚫 **개인 밴 인터페이스**\n"
            "밴하고 싶은 서번트를 **2명** 선택해줘.\n"
            "상대방은 네 선택을 볼 수 없어.",
            ephemeral=True,
            view=PrivateBanView(view.draft, view.bot_commands, self.captain_id, session_id)
        )


class PrivateBanView(discord.ui.View):
    """Private ban interface for individual captains"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', captain_id: int, session_id: str):
        super().__init__(timeout=300.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.captain_id = captain_id
        self.session_id = session_id
        self.current_category = "세이버"
        self.selected_bans = draft.captain_bans.get(captain_id, []).copy()  # Allow editing
    
    async def on_timeout(self) -> None:
        """Handle interface timeout - add reopen button to public message"""
        try:
            # Only add reopen functionality if this session is still active
            current_session = self.draft.ban_interface_sessions.get(self.captain_id)
            if current_session == self.session_id and not self.draft.captain_ban_progress.get(self.captain_id, False):
                await self.bot_commands._add_reopen_ban_interface_button(self.draft, self.captain_id)
        except Exception as e:
            logger.error(f"Error handling ban interface timeout: {e}")
        
        # Remove these broken lines that try to modify a timed-out view - Discord doesn't allow this
        # self._add_category_buttons()
        # self._add_character_dropdown()
        # self._add_confirmation_button()

    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):
            button = PrivateBanCategoryButton(category, i)
            self.add_item(button)

    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, PrivateBanCharacterDropdown):
                self.remove_item(item)
        
        # Get characters for current category (excluding already banned by other captain)
        other_captain_bans = set()
        for cap_id, bans in self.draft.captain_bans.items():
            if cap_id != self.captain_id:
                other_captain_bans.update(bans)
        
        available_in_category = [
            char for char in self.draft.servant_categories[self.current_category]
            if char not in other_captain_bans
        ]
        
        if available_in_category:
            dropdown = PrivateBanCharacterDropdown(self.draft, self.bot_commands, available_in_category, self.current_category, self.captain_id)
            # Insert before the confirmation button (which should be last)
            self.children.insert(-1, dropdown)

    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmBanButton(self.captain_id)
        self.add_item(button)

    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        ban_text = f"현재 선택: {', '.join(self.selected_bans) if self.selected_bans else '없음'} ({len(self.selected_bans)}/2)"
        
        embed = discord.Embed(
            title=f"🚫 밴 선택 - {new_category}",
            description=f"**현재 카테고리: {new_category}**\n{ban_text}",
            color=INFO_COLOR
        )
        
        # Show characters in current category
        chars_in_category = self.draft.servant_categories[new_category]
        char_list = "\n".join([f"• {char}" for char in chars_in_category])
        embed.add_field(name=f"{new_category} 서번트 목록", value=char_list, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


class PrivateBanCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private ban interface"""
    
    def __init__(self, category: str, index: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_ban_category_{category}",
            row=index // 4  # Distribute across rows
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        view: PrivateBanView = self.view
        
        # Validate session
        current_session = view.draft.ban_interface_sessions.get(view.captain_id)
        if current_session != view.session_id:
            await interaction.response.send_message(
                "이 인터페이스가 만료되었어. 새 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        await view.update_category(self.category, interaction)


class PrivateBanCharacterDropdown(discord.ui.Select):
    """Dropdown for selecting characters to ban in private interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', characters: List[str], category: str, captain_id: int):
        self.draft = draft
        self.bot_commands = bot_commands
        self.category = category
        self.captain_id = captain_id
        
        options = [
            discord.SelectOption(
                label=char, 
                value=char, 
                description=f"{category} 클래스",
                default=char in draft.captain_bans.get(captain_id, [])
            )
            for char in characters[:25]
        ]
        
        super().__init__(
            placeholder=f"{category} 서번트 밴 선택...",
            options=options,
            min_values=0,
            max_values=min(2, len(options)),
            row=4
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle character ban selection"""
        view: PrivateBanView = self.view
        
        # Validate session
        current_session = view.draft.ban_interface_sessions.get(self.captain_id)
        if current_session != view.session_id:
            await interaction.response.send_message(
                "이 인터페이스가 만료되었어. 새 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        # Update selected bans - remove previous selections from this category, add new ones
        category_chars = set(self.draft.servant_categories[self.category])
        view.selected_bans = [b for b in view.selected_bans if b not in category_chars]
        view.selected_bans.extend(self.values)
        
        # Limit to 2 total bans
        if len(view.selected_bans) > 2:
            view.selected_bans = view.selected_bans[:2]
        
        ban_text = f"현재 선택: {', '.join(view.selected_bans) if view.selected_bans else '없음'} ({len(view.selected_bans)}/2)"
        
        await interaction.response.send_message(
            f"**{self.category}**에서 선택됨: {', '.join(self.values) if self.values else '없음'}\n{ban_text}",
            ephemeral=True
        )


class ConfirmBanButton(discord.ui.Button):
    """Button to confirm ban selections"""
    
    def __init__(self, captain_id: int):
        super().__init__(
            label="밴 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_ban_{captain_id}",
            emoji="✅",
            row=4
        )
        self.captain_id = captain_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Confirm ban selections"""
        view: PrivateBanView = self.view
        
        # Validate session
        current_session = view.draft.ban_interface_sessions.get(self.captain_id)
        if current_session != view.session_id:
            await interaction.response.send_message(
                "이 인터페이스가 만료되었어. 새 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        if len(view.selected_bans) != 2:
            await interaction.response.send_message(
                f"정확히 2명을 선택해야 해. (현재: {len(view.selected_bans)}명)",
                ephemeral=True
            )
            return
        

        
        # Save bans
        view.draft.captain_bans[self.captain_id] = view.selected_bans.copy()
        view.draft.captain_ban_progress[self.captain_id] = True
        
        captain_name = view.draft.players[self.captain_id].username
        ban_list = ", ".join(view.selected_bans)
        
        await interaction.response.send_message(
            f"✅ **밴 완료!**\n"
            f"**{captain_name}**이(가) **{ban_list}**을(를) 밴했어.\n"
            "상대방이 완료할 때까지 기다려줘.",
            ephemeral=True
        )
        
        # Update public progress
        await view.bot_commands._update_ban_progress_message(view.draft)
        
        # Check if both captains completed
        if all(view.draft.captain_ban_progress.values()):
            await view.bot_commands._complete_servant_bans(view.draft)


class EphemeralSelectionView(discord.ui.View):
    """View with buttons for players to open their private selection interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=900.0)  # Longer timeout for selection
        self.draft = draft
        self.bot_commands = bot_commands
        
        # Add selection button for each player (up to 20 buttons max)
        for i, (player_id, player) in enumerate(draft.players.items()):
            if i >= 20:  # Discord button limit
                break
            button = OpenSelectionInterfaceButton(player_id, player.username, i)
            self.add_item(button)


class OpenSelectionInterfaceButton(discord.ui.Button):
    """Button for players to open their private selection interface"""
    
    def __init__(self, player_id: int, player_name: str, index: int):
        super().__init__(
            label=f"{player_name}",
            style=discord.ButtonStyle.primary,
            custom_id=f"open_selection_{player_id}",
            row=index // 5  # 5 buttons per row
        )
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open private selection interface for the player"""
        try:
            user_id = interaction.user.id
            view: EphemeralSelectionView = self.view
            
            logger.info(f"Selection interface button clicked by user {user_id} for player {self.player_id}")
            
            # In test mode, allow the real user to select for anyone
            if view.draft.is_test_mode and user_id == view.draft.real_user_id:
                logger.info(f"Test mode: allowing real user {user_id} to select for player {self.player_id}")
                pass
            elif user_id != self.player_id:
                logger.info(f"User {user_id} tried to access player {self.player_id}'s interface")
                await interaction.response.send_message(
                    "자신의 선택 인터페이스만 사용할 수 있어.", ephemeral=True
                )
                return
            
            # Generate new session ID and invalidate any existing sessions
            session_id = view.bot_commands._generate_session_id()
            view.draft.selection_interface_sessions[self.player_id] = session_id
            logger.info(f"Generated session ID {session_id} for player {self.player_id}")
            
            # Check if already completed
            player_name = view.draft.players[self.player_id].username
            current_selection = view.draft.players[self.player_id].selected_servant
            
            if view.draft.selection_progress.get(self.player_id, False):
                logger.info(f"Player {self.player_id} already completed selection: {current_selection}")
                if current_selection:
                    await interaction.response.send_message(
                        f"이미 선택을 완료했어: **{current_selection}**\n"
                        "변경하려면 다시 선택하고 확정해줘.", 
                        ephemeral=True, 
                        view=PrivateSelectionView(view.draft, view.bot_commands, self.player_id, session_id)
                    )
                else:
                    await interaction.response.send_message(
                        "선택을 완료했지만 서번트가 없어. 다시 선택해줘.", 
                        ephemeral=True,
                        view=PrivateSelectionView(view.draft, view.bot_commands, self.player_id, session_id)
                    )
                return
            
            # Open private selection interface
            logger.info(f"Opening new selection interface for player {self.player_id}")
            private_view = PrivateSelectionView(view.draft, view.bot_commands, self.player_id, session_id)
            logger.info(f"Created PrivateSelectionView with {len(private_view.children)} UI elements")
            
            await interaction.response.send_message(
                f"**{player_name}의 개인 서번트 선택**\n"
                "원하는 서번트를 한 명 선택해줘.\n"
                "다른 플레이어는 네 선택을 볼 수 없어.",
                ephemeral=True,
                view=private_view
            )
            logger.info(f"Successfully sent ephemeral selection interface to player {self.player_id}")
            
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
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', player_id: int, session_id: str):
        logger.info(f"Initializing PrivateSelectionView for player {player_id}, session {session_id}")
        super().__init__(timeout=600.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.player_id = player_id
        self.session_id = session_id
        self.current_category = "세이버"
        self.selected_servant = draft.players[player_id].selected_servant  # Allow editing
        
        try:
            # Add category buttons
            logger.info(f"Adding category buttons for player {player_id}")
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
            # Only add reopen functionality if this session is still active
            current_session = self.draft.selection_interface_sessions.get(self.player_id)
            if current_session == self.session_id and not self.draft.selection_progress.get(self.player_id, False):
                await self.bot_commands._add_reopen_selection_interface_button(self.draft, self.player_id)
        except Exception as e:
            logger.error(f"Error handling selection interface timeout: {e}")

    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):
            button = PrivateSelectionCategoryButton(category, i)
            self.add_item(button)

    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, PrivateSelectionCharacterDropdown):
                self.remove_item(item)
        
        # Get available characters for current category (exclude banned)
        available_in_category = [
            char for char in self.draft.servant_categories[self.current_category]
            if char not in self.draft.banned_servants
        ]
        
        # Check if category has any available characters
        if not available_in_category:
            # Create a disabled dropdown showing no characters available
            dropdown = EmptySelectionDropdown(self.current_category)
            self.children.insert(-1, dropdown)
        else:
            # Create normal dropdown with available characters
            dropdown = PrivateSelectionCharacterDropdown(
                self.draft, self.bot_commands, available_in_category, 
                self.current_category, self.player_id
            )
            # Insert before the confirmation button (which should be last)
            self.children.insert(-1, dropdown)

    def _add_confirmation_button(self):
        """Add confirmation button"""
        button = ConfirmSelectionButton(self.player_id)
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
        
        # Show characters in current category with ban status
        chars_in_category = self.draft.servant_categories[new_category]
        char_list = "\n".join([
            f"{'❌' if char in self.draft.banned_servants else '•'} {char}" 
            for char in chars_in_category
        ])
        embed.add_field(name=f"{new_category} 서번트 목록", value=char_list, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


class PrivateSelectionCategoryButton(discord.ui.Button):
    """Button for selecting servant category in private selection interface"""
    
    def __init__(self, category: str, index: int):
        colors = [
            discord.ButtonStyle.primary, discord.ButtonStyle.secondary, 
            discord.ButtonStyle.success, discord.ButtonStyle.danger,
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"private_selection_category_{category}",
            row=index // 4
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        # In test mode, allow the real user to interact with any player's interface
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            pass
        elif user_id != view.player_id:
            await interaction.response.send_message(
                "자신의 선택 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        
        # Validate session
        current_session = view.draft.selection_interface_sessions.get(view.player_id)
        if current_session != view.session_id:
            await interaction.response.send_message(
                "이 인터페이스가 만료되었어. 새 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        await view.update_category(self.category, interaction)





class ConfirmSelectionButton(discord.ui.Button):
    """Button to confirm servant selection"""
    
    def __init__(self, player_id: int):
        super().__init__(
            label="선택 확정",
            style=discord.ButtonStyle.success,
            custom_id=f"confirm_selection_{player_id}",
            emoji="✅",
            row=4
        )
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Confirm servant selection"""
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        # In test mode, allow the real user to interact with any player's interface
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            pass
        elif user_id != self.player_id:
            await interaction.response.send_message(
                "자신의 선택 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        
        # Validate session
        current_session = view.draft.selection_interface_sessions.get(self.player_id)
        if current_session != view.session_id:
            await interaction.response.send_message(
                "이 인터페이스가 만료되었어. 새 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        if not view.selected_servant:
            await interaction.response.send_message(
                "서번트를 먼저 선택해줘.",
                ephemeral=True
            )
            return
        
        # Save selection
        view.draft.players[self.player_id].selected_servant = view.selected_servant
        view.draft.selection_progress[self.player_id] = True
        
        player_name = view.draft.players[self.player_id].username
        
        await interaction.response.send_message(
            f"✅ **선택 완료!**\n"
            f"**{player_name}**이(가) **{view.selected_servant}**을(를) 선택했어.\n"
            "다른 플레이어들이 완료할 때까지 기다려줘.",
            ephemeral=True
        )
        
        # Update public progress
        await view.bot_commands._update_selection_progress_message(view.draft)
        
        # Check if all players completed
        if all(view.draft.selection_progress.values()):
            # Auto-complete remaining selections for test mode
            if view.draft.is_test_mode:
                await view.bot_commands._auto_complete_test_selections(view.draft)
            
            await view.bot_commands._reveal_servant_selections(view.draft)


class ReopenBanInterfaceView(discord.ui.View):
    """View with reopen button for expired ban interfaces"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', captain_id: int):
        super().__init__(timeout=None)
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
        
        # Generate new session ID and create fresh interface
        session_id = view.bot_commands._generate_session_id()
        view.draft.ban_interface_sessions[self.captain_id] = session_id
        
        # Create private ban interface
        private_view = PrivateBanView(view.draft, view.bot_commands, self.captain_id, session_id)
        
        await interaction.response.send_message(
            "🚫 **개인 밴 인터페이스 (재시도)**\n"
            "밴하고 싶은 서번트를 **2명** 선택해줘.\n"
            "상대방은 네 선택을 볼 수 없어.",
            ephemeral=True,
            view=private_view
        )


class ReopenSelectionInterfaceView(discord.ui.View):
    """View with reopen button for expired selection interfaces"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', player_id: int):
        super().__init__(timeout=None)
        self.draft = draft
        self.bot_commands = bot_commands
        self.player_id = player_id
        
        player_name = draft.players[player_id].username
        button = ReopenSelectionInterfaceButton(player_id, player_name)
        self.add_item(button)


class ReopenSelectionInterfaceButton(discord.ui.Button):
    """Button to reopen expired selection interface"""
    
    def __init__(self, player_id: int, player_name: str):
        super().__init__(
            label=f"{player_name} - 인터페이스 다시 열기",
            style=discord.ButtonStyle.secondary,
            custom_id=f"reopen_selection_{player_id}",
            emoji="🔄"
        )
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Reopen selection interface for this player"""
        view: ReopenSelectionInterfaceView = self.view
        
        # In test mode, allow the real user to select for anyone
        if view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id:
            pass
        elif interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "자신의 선택 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        
        # Check if already completed
        if view.draft.selection_progress.get(self.player_id, False):
            await interaction.response.send_message(
                "이미 선택을 완료했어.", ephemeral=True
            )
            return
        
        # Generate new session ID and create fresh interface
        session_id = view.bot_commands._generate_session_id()
        view.draft.selection_interface_sessions[self.player_id] = session_id
        
        player_name = view.draft.players[self.player_id].username
        
        # Create private selection interface
        private_view = PrivateSelectionView(view.draft, view.bot_commands, self.player_id, session_id)
        
        await interaction.response.send_message(
            f"**{player_name}의 개인 서번트 선택 (재시도)**\n"
            "원하는 서번트를 한 명 선택해줘.\n"
            "다른 플레이어는 네 선택을 볼 수 없어.",
            ephemeral=True,
            view=private_view
        )


class CaptainVotingView(discord.ui.View):
    """View for captain voting with buttons"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=300.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.user_votes: Dict[int, Set[int]] = {}  # user_id -> set of voted player_ids
        
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
                import random
                needed = 2 - len(top_players)
                if len(remaining_players) >= needed:
                    top_players.extend(random.sample(remaining_players, needed))
                else:
                    top_players.extend(remaining_players)
            elif len(top_players) > 2:
                # Too many ties, randomly select 2 from the tied players
                import random
                top_players = random.sample(top_players, 2)
            
            self.draft.captains = top_players[:2]
        else:
            # Normal mode: select top 2 vote getters
            self.draft.captains = [sorted_players[0][0], sorted_players[1][0]]
        
        # Mark them as captains and initialize progress tracking
        for captain_id in self.draft.captains:
            self.draft.players[captain_id].is_captain = True
            self.draft.captain_ban_progress[captain_id] = False
        
        # Start servant ban phase
        self.draft.phase = DraftPhase.SERVANT_BAN
        
        if self.draft.is_test_mode:
            logger.info("Detected test mode - auto-completing ban phase")
            # In test mode, automatically select random bans for captains
            import random
            all_servants = list(self.draft.available_servants)
            
            for captain_id in self.draft.captains:
                # Randomly ban 2 servants for each captain
                banned = random.sample(all_servants, min(2, len(all_servants)))
                self.draft.captain_bans[captain_id] = banned
                self.draft.banned_servants.update(banned)
                # Remove banned servants so they can't be banned again
                for servant in banned:
                    if servant in all_servants:
                        all_servants.remove(servant)
                        
                captain_name = self.draft.players[captain_id].username
                logger.info(f"Auto-banned for {captain_name}: {banned}")
            
            # Move directly to servant selection
            self.draft.phase = DraftPhase.SERVANT_SELECTION
            await self.bot_commands._start_servant_selection(self.draft)
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
        
        # Check if user is part of the draft
        if user_id not in view.draft.players:
            await interaction.response.send_message(
                "드래프트 참가자만 투표할 수 있어.", ephemeral=True
            )
            return
        
        # Initialize user votes if needed
        if user_id not in view.user_votes:
            view.user_votes[user_id] = set()
        
        # Toggle vote
        if self.player_id in view.user_votes[user_id]:
            view.user_votes[user_id].remove(self.player_id)
            await interaction.response.send_message(
                f"{view.draft.players[self.player_id].username}에 대한 투표를 취소했어.", 
                ephemeral=True
            )
        else:
            # Check vote limit (max 2 votes)
            if len(view.user_votes[user_id]) >= 2:
                await interaction.response.send_message(
                    "최대 2명까지만 투표할 수 있어.", ephemeral=True
                )
                return
            
            view.user_votes[user_id].add(self.player_id)
            await interaction.response.send_message(
                f"{view.draft.players[self.player_id].username}에게 투표했어.", 
                ephemeral=True
            )
        
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
            row=4
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """This should never be called since the dropdown is disabled"""
        await interaction.response.send_message(
            "이 카테고리는 모든 서번트가 밴되어서 선택할 수 없어.", ephemeral=True
        )


class PrivateSelectionCharacterDropdown(discord.ui.Select):
    """Dropdown for selecting characters in private interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', characters: List[str], category: str, player_id: int):
        self.draft = draft
        self.bot_commands = bot_commands
        self.category = category
        self.player_id = player_id
        
        current_selection = draft.players[player_id].selected_servant
        
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
            row=4
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle character selection"""
        view: PrivateSelectionView = self.view
        user_id = interaction.user.id
        
        # In test mode, allow the real user to interact with any player's interface
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            pass
        elif user_id != self.player_id:
            await interaction.response.send_message(
                "자신의 선택 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        
        # Validate session
        current_session = view.draft.selection_interface_sessions.get(self.player_id)
        if current_session != view.session_id:
            await interaction.response.send_message(
                "이 인터페이스가 만료되었어. 새 인터페이스를 열어줘.", ephemeral=True
            )
            return
        
        # Update selected servant
        view.selected_servant = self.values[0]
        
        await interaction.response.send_message(
            f"**{self.values[0]}** ({self.category})을(를) 선택했어!\n"
            "확정하려면 '선택 확정' 버튼을 눌러줘.",
            ephemeral=True
        )


