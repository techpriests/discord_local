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
    team_size: int = 6  # Number of players per team (2 for 2v2, 3 for 3v3, 5 for 5v5, 6 for 6v6)
    phase: DraftPhase = DraftPhase.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    
    # Thread support for clean draft environment
    thread_id: Optional[int] = None  # Thread where draft takes place
    
    # Test mode tracking
    is_test_mode: bool = False
    real_user_id: Optional[int] = None  # The real user in test mode
    
    # Captain selection
    captain_vote_message_id: Optional[int] = None
    captains: List[int] = field(default_factory=list)  # user_ids
    
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
    conflicted_servants: Dict[str, List[int]] = field(default_factory=dict)
    confirmed_servants: Dict[int, str] = field(default_factory=dict)
    
    # Team selection with confirmation support
    first_pick_captain: Optional[int] = None
    team_selection_round: int = 1
    current_picking_captain: Optional[int] = None
    picks_this_round: Dict[int, int] = field(default_factory=dict)  # captain_id -> picks_made
    pending_team_selections: Dict[int, List[int]] = field(default_factory=dict)  # captain_id -> [pending_player_ids]
    team_selection_progress: Dict[int, Dict[int, bool]] = field(default_factory=dict)  # captain_id -> {round -> completed}
    
    # Servant ban phase - enhanced for new system
    banned_servants: Set[str] = field(default_factory=set)
    system_bans: List[str] = field(default_factory=list)  # System's automated bans
    captain_bans: Dict[int, List[str]] = field(default_factory=dict)  # captain_id -> banned_servants
    captain_ban_progress: Dict[int, bool] = field(default_factory=dict)  # captain_id -> completed
    captain_ban_order: List[int] = field(default_factory=list)  # Order of captain bans determined by dice
    current_banning_captain: Optional[int] = None  # Which captain is currently banning
    
    # Servant selection progress tracking
    selection_progress: Dict[int, bool] = field(default_factory=dict)  # player_id -> completed
    reselection_round: int = 0  # Track reselection rounds to prevent infinite loops
    
    # Note: Session management removed - now using simple Discord ephemeral + user ID validation
    
    # Messages for state tracking
    status_message_id: Optional[int] = None
    ban_progress_message_id: Optional[int] = None
    selection_progress_message_id: Optional[int] = None
    selection_buttons_message_id: Optional[int] = None  # Separate message for buttons
    last_progress_update_hash: Optional[str] = field(default=None)  # Prevent unnecessary view recreation
    
    # Note: Active views tracking moved to TeamDraftCommands class for centralized memory management


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
        
        # Start cleanup task
        if bot:
            bot.loop.create_task(self._cleanup_task())
        
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
                {"first_pick": 1, "second_pick": 1},  # Round 3
                {"first_pick": 1, "second_pick": 0},  # Round 4
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
        """Clean up all message IDs to prevent memory leaks"""
        draft.captain_vote_message_id = None
        draft.status_message_id = None
        draft.ban_progress_message_id = None
        draft.selection_progress_message_id = None
        draft.selection_buttons_message_id = None
        draft.last_progress_update_hash = None
        logger.debug(f"Cleaned up all message IDs for channel {draft.channel_id}")

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
                import time
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

    # _add_reopen_ban_interface_button removed - old ban system no longer used
    # The new sequential captain ban system uses _add_reopen_captain_ban_interface_button instead

    async def _add_reopen_captain_ban_interface_button(self, draft: DraftSession, captain_id: int) -> None:
        """Add reopen interface button to captain ban progress message"""
        try:
            if draft.ban_progress_message_id:
                channel = self.bot.get_channel(draft.channel_id)
                if channel:
                    message = await channel.fetch_message(draft.ban_progress_message_id)
                    if message:
                        # Create a view with just the reopen button for this captain
                        view = ReopenCaptainBanInterfaceView(draft, self, captain_id)
                        self._register_view(draft.channel_id, view)
                        await message.edit(view=view)
        except Exception as e:
            logger.error(f"Error adding reopen captain ban interface button: {e}")

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
                   "사용법: 뮤 페어 [team_size:숫자] [captains:@유저1 @유저2]\n"
                   "예시: 뮤 페어 team_size:2 (2v2 드래프트)\n"
                   "예시: 뮤 페어 team_size:3 (3v3 드래프트)\n"
                   "예시: 뮤 페어 team_size:5 (5v5 드래프트)\n"
                   "예시: 뮤 페어 (6v6 드래프트)\n"
                   "예시: 뮤 페어 captains:@홍길동 @김철수 (팀장 지정)"
    )
    async def draft_start_chat(self, ctx: commands.Context, *, args: str = "") -> None:
        """Start team draft via chat command"""
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
        import re
        captains_match = re.search(r'captains:([^a-zA-Z]*(?:<@!?\d+>[^a-zA-Z]*){2})', args)
        if captains_match:
            captains_str = captains_match.group(1)
            
        # Pass the args to handle player mentions
        await self._handle_draft_start(ctx, args, test_mode, team_size, captains_str)

    @app_commands.command(name="페어", description="팀 드래프트를 시작해 (지원: 2v2/3v3/5v5/6v6)")
    async def draft_start_slash(
        self,
        interaction: discord.Interaction,
        players: str = "",
        test_mode: bool = False,
        team_size: int = 6,
        captains: str = ""
    ) -> None:
        """Start a new draft session"""
        # Validate team_size
        if team_size not in [2, 3, 5, 6]:
            await interaction.response.send_message(
                "팀 크기는 2 (2v2), 3 (3v3), 5 (5v5), 또는 6 (6v6)만 가능해.", ephemeral=True
            )
            return
            
        logger.info(f"페어 command called by {interaction.user.name} with test_mode={test_mode}, team_size={team_size} (v5)")
        try:
            await self._handle_draft_start(interaction, players, test_mode, team_size, captains)
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
                    await self.send_error(
                        ctx_or_interaction, 
                        f"정확히 {total_players_needed}명의 플레이어가 필요해. (현재: {len(players)}명)\n"
                        #"💡 **팁**: 테스트 모드를 사용해볼래?"
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
            "✅ **팀 드래프트 시스템이 작동해!** (v5.0)\n\n"
            "지원하는 형식:\n"
            "• `/페어 team_size:2` - 2v2 드래프트 (4명 필요)\n"
            "• `/페어 team_size:3` - 3v3 드래프트 (6명 필요)\n"
            "• `/페어 team_size:5` - 5v5 드래프트 (10명 필요)\n"
            "• `/페어` - 6v6 드래프트 (12명 필요, 기본값)\n\n"
            "새 기능:\n"
            "• `captains:@유저1 @유저2` - 팀장 수동 지정 (투표 건너뛰기)\n"
            "• 예시: `/페어 captains:@홍길동 @김철수`\n\n"
            "기타 명령어:\n"
            "• `/페어상태` - 현재 드래프트 상태 확인\n"
            "• `/페어취소` - 진행 중인 드래프트 취소\n\n",
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
        for player_id in current_draft.players.keys():
            current_draft.selection_progress[player_id] = False
        
        # Send static button message (never recreated)
        button_embed = discord.Embed(
            title="⚔️ 서번트 선택 - 플레이어 버튼",
            description="**👇 자신의 닉네임 버튼을 눌러서 서번트를 선택해!**\n"
                       "선택 내용은 모든 플레이어가 완료된 후에 공개될거야.",
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
        
        # Auto-complete fake players' selections immediately in test mode
        if current_draft.is_test_mode:
            await self._auto_complete_test_selections(current_draft)
            await self._update_selection_progress_message(current_draft)

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
                    
                    # Note: Fake players can't reopen interfaces anyway (only real user can in test mode)
                    
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
                        current_draft.selection_progress[user_id] = False  # Allow reselection
                
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
                        selected_in_category.append(f"{player.selected_servant}: {player.username}")
                
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
        
        # Remove taken servants from available list
        taken_servants = set(draft.confirmed_servants.values())
        draft.available_servants = draft.available_servants - taken_servants - draft.banned_servants
        
        embed = discord.Embed(
            title="⚔️ 서번트 선택 결과 - 중복이 있어",
            description="중복 선택된 서번트가 있네. 주사위로 결정하자.\n"
                       "일부 서번트는 확정되었고, 중복된 플레이어들은 재선택해야 해.",
            color=INFO_COLOR
        )
        
        # Show confirmed servants (locked in)
        if draft.confirmed_servants:
            confirmed_list = []
            for player_id, servant in draft.confirmed_servants.items():
                player_name = draft.players[player_id].username
                confirmed_list.append(f"🔒 {servant}: {player_name}")
            embed.add_field(
                name="✅ 확정된 서번트 (수정 불가)",
                value="\n".join(confirmed_list),
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
        
        # Auto-complete reselection for fake players in test mode
        if draft.is_test_mode:
            await self._auto_complete_reselection(draft)

    async def _auto_complete_reselection(self, draft: DraftSession) -> None:
        """Auto-complete servant reselection for fake players in test mode"""
        import random
        
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
        for player_id in conflicted_players:
            player = draft.players[player_id]
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
        """Start servant ban phase with automated system bans followed by captain bans"""
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
        if not channel:
            logger.warning("Could not get draft channel for servant ban phase")
            return
        
        # Step 1: Perform automated system bans
        await self._perform_system_bans(draft, channel)
        
        # Step 2: Determine captain ban order with dice roll
        await self._determine_captain_ban_order(draft, channel)
        
        # Step 3: Start captain ban phase
        await self._start_captain_bans(draft, channel)

    async def _perform_system_bans(self, draft: DraftSession, channel) -> None:
        """Perform automated system bans before captain bans"""
        import random
        
        system_bans = []
        
        # Get available servants for each tier (exclude already banned)
        available_s_tier = [s for s in draft.servant_tiers["S"] if s in draft.available_servants]
        available_a_tier = [s for s in draft.servant_tiers["A"] if s in draft.available_servants]
        available_b_tier = [s for s in draft.servant_tiers["B"] if s in draft.available_servants]
        
        # 2 random from S tier (if possible)
        s_bans = []
        for _ in range(min(2, len(available_s_tier))):
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
        
        await self._safe_api_call(
            lambda: channel.send(embed=embed),
            bucket=f"system_bans_{draft.channel_id}"
        )

    async def _determine_captain_ban_order(self, draft: DraftSession, channel) -> None:
        """Determine captain ban order using dice roll"""
        import random
        
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
        
        # Find the channel and send the initial ban results
        channel = self.bot.get_channel(draft.channel_id)
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
        
        # Note: With new simple ID verification, no session invalidation needed
        
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
                if draft.phase in [DraftPhase.FINAL_SWAP, DraftPhase.TEAM_SELECTION]:
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
        
        # Send to thread
        await self._safe_api_call(
            lambda: channel.send(embed=embed),
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
                               "모든 플레이어들 수고했어! 🎉",
                    color=SUCCESS_COLOR
                )
                
                main_embed.add_field(name="팀 1 최종 로스터", value=format_final_team(team1_players), inline=True)
                main_embed.add_field(name="팀 2 최종 로스터", value=format_final_team(team2_players), inline=True)
                
                # Add draft summary
                total_time = time.time() - self.draft_start_times.get(current_draft.channel_id, time.time())
                minutes = int(total_time // 60)
                main_embed.add_field(
                    name="드래프트 정보",
                    value=f"⏱️ 소요 시간: 약 {minutes}분\n"
                          f"👥 참가자: {len(current_draft.players)}명\n"
                          f"🎯 형식: {team_format}",
                    inline=False
                )
                
                await self._safe_api_call(
                    lambda: main_channel.send(embed=main_embed),
                    bucket=f"draft_complete_main_{current_draft.channel_id}"
                )
            except Exception as e:
                logger.warning(f"Failed to send final roster to main channel: {e}")
        
        # Clean up with comprehensive memory management
        if current_channel_id in self.active_drafts:
            draft = self.active_drafts[current_channel_id]
            
            # Stop all active views to prevent memory leaks
            await self._cleanup_views(current_channel_id)
            
            # Clean up all message IDs to prevent memory leaks
            await self._cleanup_all_message_ids(draft)
            
            del self.active_drafts[current_channel_id]
        if current_channel_id in self.draft_start_times:
            del self.draft_start_times[current_channel_id]
        
        logger.info(f"Draft completed in channel {current_channel_id} with full cleanup")

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
        
        # Use thread if available, otherwise main channel
        channel = self._get_draft_channel(draft)
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
                f"{draft.confirmed_servants[p.user_id]} - {p.username}"
                for p in players
            ])
        
        embed.add_field(name="팀 1 최종 로스터", value=format_final_team(team1_players), inline=True)
        embed.add_field(name="팀 2 최종 로스터", value=format_final_team(team2_players), inline=True)
        
        view = FinalSwapView(draft, self)
        self._register_view(draft.channel_id, view)
        await self._safe_api_call(
            lambda: channel.send(embed=embed, view=view),
            bucket=f"final_swap_{draft.channel_id}"
        )


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
        
        # Validate it's still the captain's turn
        if view.draft.current_picking_captain != current_captain:
            await interaction.response.send_message(
                "지금은 네 차례가 아니야.", ephemeral=True
            )
            return
        
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
            placeholder="팀원 선택(주의: 메뉴에서 고르자마자 선택이 확정돼!)",
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
        super().__init__(timeout=1800.0)  # 30 minutes
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
        
        # Validate current phase - reject if not in final swap phase
        if view.draft.phase != DraftPhase.FINAL_SWAP:
            await interaction.response.send_message(
                "최종 교체 단계가 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", ephemeral=True
            )
            return
        
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
            # In test mode, the real user can act as any captain for any team
            is_captain = True
            user_team = self.team_number  # Override team check in test mode
        
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
            await view.bot_commands._complete_draft(view.draft)


# OLD BAN SYSTEM CLASSES REMOVED
# The following classes have been removed and replaced with the new sequential captain ban system:
# - EphemeralBanView (replaced by EphemeralCaptainBanView)
# - OpenBanInterfaceButton (replaced by OpenCaptainBanInterfaceButton)  
# - PrivateBanView (replaced by PrivateCaptainBanView)
# - PrivateBanCategoryButton (replaced by PrivateCaptainBanCategoryButton)
# - PrivateBanCharacterDropdown (replaced by PrivateCaptainBanCharacterDropdown)
# - ConfirmBanButton (replaced by ConfirmCaptainBanButton)
# 
# The new system supports:
# - 3 automated system bans (1 from S, A, B tiers)
# - Sequential captain bans (1 each) determined by dice roll
# - Real-time public announcement of bans as they happen


class EphemeralSelectionView(discord.ui.View):
    """View with buttons for players to open their private selection interface"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=1800.0)  # 30 minutes
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
            
            # During reselection phase, only allow conflicted players to re-select
            if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
                conflicted_players = set()
                for user_ids in view.draft.conflicted_servants.values():
                    conflicted_players.update(user_ids)
                
                # In test mode, allow real user to access any player's interface for testing
                if self.player_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                    player_name = view.draft.players[self.player_id].username
                    await interaction.response.send_message(
                        f"**{player_name}**은(는) 재선택 대상이 아니야.\n"
                        "중복으로 인해 재선택이 필요한 플레이어만 변경할 수 있어.", ephemeral=True
                    )
                    return
            
            # No session management needed - Discord ephemeral + user ID validation provides security
            
            # Check if already completed
            player_name = view.draft.players[self.player_id].username
            current_selection = view.draft.players[self.player_id].selected_servant
            
            if view.draft.selection_progress.get(self.player_id, False):
                logger.info(f"Player {self.player_id} already completed selection: {current_selection}")
                
                # Security: Never reveal servant choice to other players, even in edge cases
                if user_id != self.player_id and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                    await interaction.response.send_message(
                        "이미 선택을 완료했어.", 
                        ephemeral=True
                    )
                    return
                
                # Safe to show detailed info only to the actual player (or test mode real user)
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
            logger.info(f"Opening new selection interface for player {self.player_id}")
            private_view = PrivateSelectionView(view.draft, view.bot_commands, self.player_id)
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
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', player_id: int):
        logger.info(f"Initializing PrivateSelectionView for player {player_id}")
        super().__init__(timeout=1800.0)  # 30 minutes
        self.draft = draft
        self.bot_commands = bot_commands
        self.player_id = player_id
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
            # Add reopen functionality if player hasn't completed selection yet
            if not self.draft.selection_progress.get(self.player_id, False):
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
                self.current_category, self.player_id
            )
            self.add_item(dropdown)

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
        
        logger.info(f"Category '{self.category}' clicked by user {user_id} for player {view.player_id}")
        
        # In test mode, allow the real user to interact with any player's interface
        if view.draft.is_test_mode and user_id == view.draft.real_user_id:
            pass
        elif user_id != view.player_id:
            await interaction.response.send_message(
                "자신의 선택 인터페이스만 사용할 수 있어.", ephemeral=True
            )
            return
        
        # SIMPLIFIED SECURITY MODEL: State validation without complex session management
        # 
        # Security is provided by 3 simple layers:
        # 1. Discord's ephemeral messages (only recipient can see/interact)
        # 2. User ID validation (checked above) 
        # 3. State validation (below) - prevents wrong phase/completed interactions
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
        if view.draft.selection_progress.get(view.player_id, False):
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
            
            if view.player_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                player_name = view.draft.players[view.player_id].username
                await interaction.response.send_message(
                    f"**{player_name}**은(는) 재선택 대상이 아니야.\n"
                    "중복으로 인해 재선택이 필요한 플레이어만 변경할 수 있어.", ephemeral=True
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
        
        # During reselection phase, only allow conflicted players to confirm
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            conflicted_players = set()
            for user_ids in view.draft.conflicted_servants.values():
                conflicted_players.update(user_ids)
            
            # In test mode, allow real user to confirm for any player for testing
            if self.player_id not in conflicted_players and not (view.draft.is_test_mode and user_id == view.draft.real_user_id):
                player_name = view.draft.players[self.player_id].username
                await interaction.response.send_message(
                    f"**{player_name}**은(는) 재선택 대상이 아니야.\n"
                    "중복으로 인해 재선택이 필요한 플레이어만 변경할 수 있어.", ephemeral=True
                )
                return
        
        # Simple state validation
        # 1. Completion validation - prevent double confirmation
        if view.draft.selection_progress.get(self.player_id, False):
            await interaction.response.send_message(
                "이미 선택을 완료했어.", ephemeral=True
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
        logger.info(f"Player {self.player_id} completed selection: {view.selected_servant}")
        
        await interaction.response.send_message(
            f"✅ **선택 완료!**\n"
            f"**{player_name}**이(가) **{view.selected_servant}**을(를) 선택했어.\n"
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


class ReopenSelectionInterfaceView(discord.ui.View):
    """View with reopen button for expired selection interfaces"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', player_id: int):
        super().__init__(timeout=1800.0)  # 30 minutes
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
        
        # During reselection phase, only allow conflicted players to reopen interface
        if view.draft.phase == DraftPhase.SERVANT_RESELECTION:
            conflicted_players = set()
            for user_ids in view.draft.conflicted_servants.values():
                conflicted_players.update(user_ids)
            
            # In test mode, allow real user to access any player's interface for testing
            if self.player_id not in conflicted_players and not (view.draft.is_test_mode and interaction.user.id == view.draft.real_user_id):
                player_name = view.draft.players[self.player_id].username
                await interaction.response.send_message(
                    f"**{player_name}**은(는) 재선택 대상이 아니야.\n"
                    "중복으로 인해 재선택이 필요한 플레이어만 인터페이스를 다시 열 수 있어.", ephemeral=True
                )
                return
        
        player_name = view.draft.players[self.player_id].username
        
        # Create private selection interface
        private_view = PrivateSelectionView(view.draft, view.bot_commands, self.player_id)
        
        await interaction.response.send_message(
            f"**{player_name}의 개인 서번트 선택 (재시도)**\n"
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
            row=3
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
            row=3
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
        
        # Simple state validation - no complex session management needed
        
        # 1. Phase validation - prevent interaction if wrong phase
        if view.draft.phase not in [DraftPhase.SERVANT_SELECTION, DraftPhase.SERVANT_RESELECTION]:
            await interaction.response.send_message(
                "이 선택 단계는 이미 끝났어. 이 인터페이스는 더 이상 사용할 수 없어.", 
                ephemeral=True
            )
            return
        
        # 2. Completion validation - prevent changes after confirmation
        if view.draft.selection_progress.get(self.player_id, False):
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
        import random
        
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


