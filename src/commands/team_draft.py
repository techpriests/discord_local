import logging
import random
import asyncio
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
    captain_votes: int = 0
    protected: bool = False


@dataclass
class DraftSession:
    """Represents an active draft session"""
    channel_id: int
    guild_id: int
    phase: DraftPhase = DraftPhase.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    
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
    bans_submitted: Set[int] = field(default_factory=set)  # captain_ids who submitted bans
    
    # Messages for state tracking
    status_message_id: Optional[int] = None


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
        
        # Selection patterns for team picking
        self.team_selection_pattern = [
            {"first_pick": 1, "second_pick": 2},  # Round 1
            {"first_pick": 2, "second_pick": 2},  # Round 2
            {"first_pick": 1, "second_pick": 1},  # Round 3
            {"first_pick": 1, "second_pick": 0},  # Round 4
        ]

    @commands.command(
        name="페어",
        help="12명의 플레이어와 함께 팀 드래프트를 시작합니다",
        brief="팀 드래프트 시작",
        aliases=["draft", "팀드래프트"],
        description="팀 드래프트 시스템을 시작합니다.\n"
                   "사용법: 뮤 페어 [test_mode:True] - 테스트 모드\n"
                   "예시: 뮤 페어 test_mode:True"
    )
    async def draft_start_chat(self, ctx: commands.Context, *, args: str = "") -> None:
        """Start team draft via chat command"""
        # Parse test_mode from args
        test_mode = "test_mode:true" in args.lower() or "test_mode=true" in args.lower()
        await self._handle_draft_start(ctx, "", test_mode)

    @app_commands.command(name="페어", description="12명의 플레이어와 함께 팀 드래프트를 시작합니다")
    async def draft_start_slash(
        self,
        interaction: discord.Interaction,
        players: str = "",
        test_mode: bool = False
    ) -> None:
        """Start a new draft session"""
        logger.info(f"페어 command called by {interaction.user.name} with test_mode={test_mode} (v2)")
        try:
            await self._handle_draft_start(interaction, players, test_mode)
        except Exception as e:
            logger.error(f"Error in draft_start_slash: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⚠️ 명령어 실행 중 오류가 발생했습니다: {str(e)}", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ 명령어 실행 중 오류가 발생했습니다: {str(e)}", 
                    ephemeral=True
                )

    @command_handler()
    async def _handle_draft_start(
        self,
        ctx_or_interaction: CommandContext,
        players_str: str = "",
        test_mode: bool = False
    ) -> None:
        """Handle draft start command"""
        try:
            channel_id = self.get_channel_id(ctx_or_interaction)
            guild_id = self.get_guild_id(ctx_or_interaction)
            
            if channel_id in self.active_drafts:
                await self.send_error(ctx_or_interaction, "이미 진행 중인 드래프트가 있습니다.")
                return
                
            if not guild_id:
                await self.send_error(ctx_or_interaction, "서버에서만 드래프트를 시작할 수 있습니다.")
                return
            
            # Handle test mode or real players
            if test_mode:
                players = await self._generate_test_players(ctx_or_interaction)
                await self.send_success(
                    ctx_or_interaction, 
                    "🧪 **테스트 모드**V2로 드래프트를 시작합니다!\n"
                    "가상의 플레이어 12명이 자동으로 생성되었습니다."
                )
            else:
                # Parse player mentions
                players = await self._parse_players(ctx_or_interaction, players_str)
                
                if len(players) != 12:
                    await self.send_error(
                        ctx_or_interaction, 
                        f"정확히 12명의 플레이어가 필요합니다. (현재: {len(players)}명)\n"
                        #"💡 **팁**: `t`로 테스트 모드를 사용해보세요!"
                    )
                    return
            
            # Create draft session
            draft = DraftSession(channel_id=channel_id, guild_id=guild_id)
            for user_id, username in players:
                draft.players[user_id] = Player(user_id=user_id, username=username)
            
            self.active_drafts[channel_id] = draft
            
            # Start captain voting
            await self._start_captain_voting(ctx_or_interaction, draft)
            
        except Exception as e:
            logger.error(f"Error starting draft: {e}")
            await self.send_error(ctx_or_interaction, "드래프트 시작 중 오류가 발생했습니다.")

    async def _generate_test_players(self, ctx_or_interaction: CommandContext) -> List[Tuple[int, str]]:
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
        
        # Add the real user as first player
        players.append((real_user_id, real_username))
        
        # Generate 11 fake players with fake IDs
        import random
        for i in range(11):
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
            description="모든 플레이어는 팀장으로 추천하고 싶은 2명에게 투표하세요.\n"
                       "가장 많은 표를 받은 2명이 팀장이 됩니다.",
            color=INFO_COLOR
        )
        
        player_list = "\n".join([f"{i+1}. {player.username}" 
                                for i, player in enumerate(draft.players.values())])
        embed.add_field(name="참가자 목록", value=player_list, inline=False)
        embed.add_field(name="투표 방법", value="아래 번호 버튼을 눌러 투표하세요", inline=False)
        
        # Create voting view
        view = CaptainVotingView(draft, self)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            if ctx_or_interaction.response.is_done():
                message = await ctx_or_interaction.followup.send(embed=embed, view=view)
            else:
                await ctx_or_interaction.response.send_message(embed=embed, view=view)
                message = await ctx_or_interaction.original_response()
        else:
            message = await ctx_or_interaction.send(embed=embed, view=view)
        
        draft.captain_vote_message_id = message.id

    @app_commands.command(name="페어상태", description="현재 드래프트 상태를 확인합니다")
    async def draft_status_slash(self, interaction: discord.Interaction) -> None:
        """Check current draft status"""
        await self._handle_draft_status(interaction)

    @commands.command(
        name="페어상태",
        help="현재 드래프트 상태를 확인합니다",
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
            await self.send_error(ctx_or_interaction, "진행 중인 드래프트가 없습니다.")
            return
        
        draft = self.active_drafts[channel_id]
        embed = await self._create_status_embed(draft)
        await self.send_response(ctx_or_interaction, embed=embed)

    async def _create_status_embed(self, draft: DraftSession) -> discord.Embed:
        """Create status embed for current draft state"""
        embed = discord.Embed(title="🏆 드래프트 현황", color=INFO_COLOR)
        
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
                value=f"{confirmed_count}/12 완료",
                inline=True
            )
        
        return embed 

    @app_commands.command(name="페어취소", description="진행 중인 드래프트를 취소합니다")
    async def draft_cancel_slash(self, interaction: discord.Interaction) -> None:
        """Cancel current draft"""
        await self._handle_draft_cancel(interaction)

    @commands.command(
        name="페어취소",
        help="진행 중인 드래프트를 취소합니다",
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
            "✅ **팀 드래프트 시스템이 작동합니다!** (v3.0)\n\n"
            "사용법:\n"
            "• `/페어 test_mode:True` - 테스트 모드로 드래프트 시작\n"
            "• `/페어상태` - 현재 드래프트 상태 확인",
            ephemeral=True
        )

    async def _start_servant_selection(self) -> None:
        """Start servant selection phase"""
        # Find the channel and draft
        channel = None
        current_draft = None
        for channel_id, draft in self.active_drafts.items():
            if draft.phase == DraftPhase.SERVANT_SELECTION:
                try:
                    channel = self.bot.get_channel(channel_id)
                    current_draft = draft
                    break
                except Exception as e:
                    logger.error(f"Error getting channel {channel_id}: {e}")
                    continue
        
        if not channel or not current_draft:
            logger.warning(f"Could not find channel or draft. channel: {channel}, current_draft: {current_draft}")
            return
        
        # Remove banned servants from available list
        current_draft.available_servants = current_draft.available_servants - current_draft.banned_servants
        
        embed = discord.Embed(
            title="⚔️ 서번트 선택",
            description="**현재 카테고리: 세이버**\n"
                       "카테고리 버튼을 눌러 다른 클래스를 선택하거나,\n"
                       "아래 드롭다운에서 서번트를 선택하세요.\n"
                       "❌ 표시된 서번트는 밴되어 선택할 수 없습니다.",
            color=INFO_COLOR
        )
        
        # Show characters in default category (세이버) with ban status
        saber_chars = current_draft.servant_categories["세이버"]
        char_list = "\n".join([
            f"{'❌' if char in current_draft.banned_servants else '•'} {char}" 
            for char in saber_chars
        ])
        embed.add_field(name="세이버 서번트 목록", value=char_list, inline=False)
        
        # Show banned servants summary
        if current_draft.banned_servants:
            banned_list = ", ".join(sorted(current_draft.banned_servants))
            embed.add_field(name="🚫 밴된 서번트", value=banned_list, inline=False)
        
        embed.add_field(
            name="📋 선택 방법",
            value="1️⃣ 원하는 **카테고리 버튼**을 클릭\n"
                  "2️⃣ 해당 카테고리의 **드롭다운**에서 서번트 선택\n"
                  "3️⃣ 모든 플레이어가 선택 완료시 결과 공개",
            inline=False
        )
        
        view = ServantSelectionView(current_draft, self)
        await channel.send(embed=embed, view=view)

    async def _reveal_servant_selections(self) -> None:
        """Reveal servant selections and handle conflicts"""
        # Find the current draft
        current_draft = None
        current_channel_id = None
        for channel_id, draft in self.active_drafts.items():
            if draft.phase == DraftPhase.SERVANT_SELECTION:
                current_draft = draft
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
                title="🎲 서번트 선택 결과 - 중복 발생!",
                description="중복 선택된 서번트가 있습니다. 주사위로 결정합니다.",
                color=ERROR_COLOR
            )
            
            for servant, user_ids in conflicts.items():
                # Roll dice for each conflicted user
                rolls = {}
                for user_id in user_ids:
                    rolls[user_id] = random.randint(1, 20)
                
                # Find winner (highest roll)
                winner_id = max(rolls.keys(), key=lambda uid: rolls[uid])
                
                # Set winner and reset losers
                current_draft.confirmed_servants[winner_id] = servant
                current_draft.conflicted_servants[servant] = [uid for uid in user_ids if uid != winner_id]
                
                # Reset losers' selections
                for user_id in user_ids:
                    if user_id != winner_id:
                        current_draft.players[user_id].selected_servant = None
                
                # Add to embed
                roll_text = "\n".join([
                    f"{current_draft.players[uid].username}: {roll} {'✅' if uid == winner_id else '❌'}"
                    for uid, roll in rolls.items()
                ])
                embed.add_field(name=f"{servant} 중복", value=roll_text, inline=True)
            
            # Confirm non-conflicted servants
            for servant, user_ids in servant_users.items():
                if len(user_ids) == 1:
                    current_draft.confirmed_servants[user_ids[0]] = servant
            
            await channel.send(embed=embed)
            
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
                description="모든 플레이어의 서번트 선택이 완료되었습니다!",
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
            
            await channel.send(embed=embed)
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
            description="중복으로 인해 서번트를 다시 선택해야 하는 플레이어들이 있습니다.\n"
                       "**현재 카테고리: 세이버**\n"
                       "❌ 표시된 서번트는 이미 선택되었거나 밴되어 선택할 수 없습니다.",
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
            value="1️⃣ **카테고리 버튼**으로 클래스 변경\n"
                  "2️⃣ **드롭다운**에서 사용 가능한 서번트 선택\n"
                  "❌ 표시된 서번트는 이미 선택됨",
            inline=False
        )
        
        view = ServantSelectionView(draft, self, True)
        await channel.send(embed=embed, view=view)

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
            description="팀장들이 순서대로 팀원을 선택합니다.",
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
        
        await channel.send(embed=embed)
        await self._continue_team_selection_for_draft(draft)

    async def _continue_team_selection_for_draft(self, draft: DraftSession) -> None:
        """Continue team selection process for a specific draft"""
        # Check if team selection is complete
        assigned_players = sum(1 for p in draft.players.values() if p.team is not None)
        if assigned_players == 12:
            await self._start_final_swap_phase_for_draft(draft)
            return
        
        # Get current round pattern
        round_info = self.team_selection_pattern[draft.team_selection_round - 1]
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
        round_info = self.team_selection_pattern[draft.team_selection_round - 1]
        
        embed = discord.Embed(
            title=f"👥 팀 선택 - 라운드 {draft.team_selection_round}",
            description=f"현재 {draft.players[current_captain].username}의 차례입니다.",
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
        await channel.send(embed=embed, view=view)

    @command_handler()
    async def _handle_draft_cancel(self, ctx_or_interaction: CommandContext) -> None:
        """Handle draft cancellation"""
        channel_id = self.get_channel_id(ctx_or_interaction)
        
        if channel_id not in self.active_drafts:
            await self.send_error(ctx_or_interaction, "진행 중인 드래프트가 없습니다.")
            return
        
        del self.active_drafts[channel_id]
        await self.send_success(ctx_or_interaction, "드래프트가 취소되었습니다.")

    async def _start_servant_ban_phase(self, draft: DraftSession) -> None:
        """Start servant ban phase where captains ban 2 servants each"""
        # Find the channel for this draft
        channel = None
        for channel_id, d in self.active_drafts.items():
            if d == draft:
                channel = self.bot.get_channel(channel_id)
                break
        
        if not channel:
            logger.warning("Could not find channel for servant ban phase")
            return
        
        embed = discord.Embed(
            title="🚫 서번트 밴 단계",
            description="각 팀장은 밴하고 싶은 서번트를 **2명**씩 선택하세요.\n"
                       "상대방이 어떤 서번트를 밴하는지 모르는 상태에서 진행됩니다.",
            color=INFO_COLOR
        )
        
        captain_names = [draft.players[cap_id].username for cap_id in draft.captains]
        embed.add_field(name="팀장", value=" vs ".join(captain_names), inline=False)
        
        embed.add_field(
            name="📋 밴 방법",
            value="1️⃣ 아래 **카테고리 버튼**을 클릭\n"
                  "2️⃣ 해당 카테고리의 **드롭다운**에서 서번트 선택\n"
                  "3️⃣ **2명**을 선택한 후 확정 버튼 클릭\n"
                  "4️⃣ 양 팀장 모두 완료시 밴 결과 공개",
            inline=False
        )
        
        view = ServantBanView(draft, self)
        await channel.send(embed=embed, view=view)

    async def _complete_servant_bans(self, draft: DraftSession) -> None:
        """Complete servant ban phase and reveal banned servants"""
        # Collect all banned servants
        all_bans = []
        for captain_id, bans in draft.captain_bans.items():
            all_bans.extend(bans)
            draft.banned_servants.update(bans)
        
        embed = discord.Embed(
            title="🚫 서번트 밴 결과",
            description="양 팀장의 밴이 완료되었습니다. 다음 서번트들이 밴되었습니다.",
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
            await channel.send(embed=embed)
        
        # Move to servant selection phase
        draft.phase = DraftPhase.SERVANT_SELECTION
        await self._start_servant_selection()

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
            description="모든 단계가 완료되었습니다. 게임을 시작하세요!",
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
        
        await channel.send(embed=embed)
        
        # Clean up
        if current_channel_id in self.active_drafts:
            del self.active_drafts[current_channel_id]

    async def _check_voting_completion(self, view: 'CaptainVotingView') -> bool:
        """Check if voting should be completed"""
        # Check if all players have voted (normal case)
        if len(view.user_votes) == len(view.draft.players):
            return True
        
        # For test mode: check if the real user has voted for 2 people
        # In test mode, only 1 real player can vote
        if len(view.user_votes) == 1:  # Only one person has voted
            user_votes = list(view.user_votes.values())[0]
            if len(user_votes) == 2:  # They voted for 2 people
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
            description="각 팀은 팀 내에서 서번트를 자유롭게 교체할 수 있습니다.\n"
                       "교체를 원하지 않으면 완료 버튼을 눌러주세요.",
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
        await channel.send(embed=embed, view=view)


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
            placeholder="팀원을 선택하세요...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle player selection"""
        user_id = interaction.user.id
        
        if user_id != self.draft.current_picking_captain:
            await interaction.response.send_message(
                "현재 귀하의 차례가 아닙니다.", ephemeral=True
            )
            return
        
        selected_player_id = int(self.values[0])
        target_player = self.draft.players[selected_player_id]
        
        # Assign player to team
        captain_team = self.draft.players[user_id].team
        target_player.team = captain_team
        
        # Update pick count
        self.draft.picks_this_round[user_id] += 1
        
        await interaction.response.send_message(
            f"**{target_player.username}**을(를) 팀에 추가했습니다!", ephemeral=False
        )
        
        # Continue team selection
        await self.bot_commands._continue_team_selection_for_draft(self.draft)


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
        user_team = view.draft.players.get(user_id, {}).team if user_id in view.draft.players else None
        is_captain = view.draft.players.get(user_id, {}).is_captain if user_id in view.draft.players else False
        
        if not is_captain or user_team != self.team_number:
            await interaction.response.send_message(
                f"팀 {self.team_number}의 팀장만 완료할 수 있습니다.", ephemeral=True
            )
            return
        
        view.team_ready[self.team_number] = True
        self.disabled = True
        
        await interaction.response.edit_message(view=view)
        
        # Check if both teams are ready
        if all(view.team_ready.values()):
            await view.bot_commands._complete_draft()


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
        
        # Mark them as captains
        for captain_id in self.draft.captains:
            self.draft.players[captain_id].is_captain = True
        
        # Start servant ban phase
        self.draft.phase = DraftPhase.SERVANT_BAN
        
        # Check if this is test mode (only 1 real user among 12 players)
        real_users = [user_id for user_id in self.draft.players.keys() if user_id < 1000000000000000000]  # Real Discord IDs are typically smaller
        
        if len(real_users) <= 1:  # Test mode - auto-complete ban phase
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
            
            # Move directly to servant selection
            self.draft.phase = DraftPhase.SERVANT_SELECTION
            await self.bot_commands._start_servant_selection()
        else:
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
                "드래프트 참가자만 투표할 수 있습니다.", ephemeral=True
            )
            return
        
        # Initialize user votes if needed
        if user_id not in view.user_votes:
            view.user_votes[user_id] = set()
        
        # Toggle vote
        if self.player_id in view.user_votes[user_id]:
            view.user_votes[user_id].remove(self.player_id)
            await interaction.response.send_message(
                f"{view.draft.players[self.player_id].username}에 대한 투표를 취소했습니다.", 
                ephemeral=True
            )
        else:
            # Check vote limit (max 2 votes)
            if len(view.user_votes[user_id]) >= 2:
                await interaction.response.send_message(
                    "최대 2명까지만 투표할 수 있습니다.", ephemeral=True
                )
                return
            
            view.user_votes[user_id].add(self.player_id)
            await interaction.response.send_message(
                f"{view.draft.players[self.player_id].username}에게 투표했습니다.", 
                ephemeral=True
            )
        
        # Check if voting should be completed
        should_complete = await view.bot_commands._check_voting_completion(view)
        if should_complete:
            await view._finalize_voting()


class ServantSelectionView(discord.ui.View):
    """View for servant selection with category pagination"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', is_reselection: bool = False):
        super().__init__(timeout=600.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.is_reselection = is_reselection
        self.current_category = "세이버"  # Default category
        
        # Add category buttons
        self._add_category_buttons()
        # Add character dropdown for current category
        self._add_character_dropdown()

    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):  # Max 8 categories
            button = CategoryButton(category, i)
            self.add_item(button)

    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, CharacterDropdown):
                self.remove_item(item)
        
        # Get available characters for current category
        if self.is_reselection:
            # For reselection, only show available (not taken) characters
            taken_servants = set(self.draft.confirmed_servants.values())
            available_in_category = [
                char for char in self.draft.servant_categories[self.current_category]
                if char in self.draft.available_servants and char not in taken_servants
            ]
        else:
            # For initial selection, show all characters in category that aren't banned
            available_in_category = [
                char for char in self.draft.servant_categories[self.current_category]
                if char not in self.draft.banned_servants
            ]
        
        if available_in_category:
            dropdown = CharacterDropdown(self.draft, self.bot_commands, available_in_category, self.current_category)
            self.add_item(dropdown)

    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        # Update embed to show current category
        title = "🔄 서번트 재선택" if self.is_reselection else "⚔️ 서번트 선택"
        embed = discord.Embed(
            title=title,
            description=f"**현재 카테고리: {new_category}**\n"
                       "아래 드롭다운에서 서번트를 선택하세요.\n"
                       "❌ 표시된 서번트는 밴되어 선택할 수 없습니다.",
            color=INFO_COLOR
        )
        
        # Show characters in current category
        chars_in_category = self.draft.servant_categories[new_category]
        if self.is_reselection:
            taken_servants = set(self.draft.confirmed_servants.values())
            char_list = "\n".join([
                f"{'❌' if char in taken_servants or char in self.draft.banned_servants else '✅'} {char}" 
                for char in chars_in_category
            ])
        else:
            char_list = "\n".join([
                f"{'❌' if char in self.draft.banned_servants else '•'} {char}" 
                for char in chars_in_category
            ])
        
        embed.add_field(name=f"{new_category} 서번트 목록", value=char_list, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        """Handle timeout"""
        for item in self.children:
            item.disabled = True


class CategoryButton(discord.ui.Button):
    """Button for selecting servant category"""
    
    def __init__(self, category: str, index: int):
        # Use different colors for different categories
        colors = [
            discord.ButtonStyle.primary,   # Blue
            discord.ButtonStyle.secondary, # Gray
            discord.ButtonStyle.success,   # Green
            discord.ButtonStyle.danger,    # Red
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"category_{category}"
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        view: ServantSelectionView = self.view
        await view.update_category(self.category, interaction)


class CharacterDropdown(discord.ui.Select):
    """Dropdown for selecting characters within a category"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', characters: List[str], category: str):
        self.draft = draft
        self.bot_commands = bot_commands
        self.category = category
        
        # Create options for available characters in this category
        options = [
            discord.SelectOption(label=char, value=char, description=f"{category} 클래스")
            for char in characters[:25]  # Discord limit
        ]
        
        super().__init__(
            placeholder=f"{category} 서번트를 선택하세요...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle character selection"""
        user_id = interaction.user.id
        
        # Check if user is part of the draft
        if user_id not in self.draft.players:
            await interaction.response.send_message(
                "드래프트 참가자만 서번트를 선택할 수 있습니다.", ephemeral=True
            )
            return
        
        # Check if user already selected (for initial selection)
        if user_id in self.draft.confirmed_servants:
            await interaction.response.send_message(
                "이미 서번트를 선택했습니다.", ephemeral=True
            )
            return
        
        selected_character = self.values[0]
        self.draft.players[user_id].selected_servant = selected_character
        
        await interaction.response.send_message(
            f"**{selected_character}** ({self.category})를 선택했습니다!", ephemeral=True
        )
        
        # Check if all players have selected
        selected_count = sum(1 for p in self.draft.players.values() if p.selected_servant)
        if selected_count == 12:
            # All selected, reveal and check for conflicts
            view: ServantSelectionView = self.view
            await view.bot_commands._reveal_servant_selections()
        else:
            # Continue to next category
            await view.update_category(self.category, interaction) 


class ServantBanView(discord.ui.View):
    """View for servant ban selection"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands'):
        super().__init__(timeout=300.0)
        self.draft = draft
        self.bot_commands = bot_commands
        self.current_category = "세이버"  # Default category
        
        # Add category buttons
        self._add_category_buttons()
        # Add character dropdown for current category
        self._add_character_dropdown()

    def _add_category_buttons(self):
        """Add category selection buttons"""
        categories = list(self.draft.servant_categories.keys())
        
        for i, category in enumerate(categories[:8]):  # Max 8 categories
            button = BanCategoryButton(category, i)
            self.add_item(button)

    def _add_character_dropdown(self):
        """Add character selection dropdown for current category"""
        # Remove existing character dropdown if any
        for item in self.children[:]:
            if isinstance(item, BanCharacterDropdown):
                self.remove_item(item)
        
        # Get characters for current category (excluding already banned)
        available_in_category = [
            char for char in self.draft.servant_categories[self.current_category]
            if char not in self.draft.banned_servants
        ]
        
        if available_in_category:
            dropdown = BanCharacterDropdown(self.draft, self.bot_commands, available_in_category, self.current_category)
            self.add_item(dropdown)

    async def update_category(self, new_category: str, interaction: discord.Interaction):
        """Update the current category and refresh the dropdown"""
        self.current_category = new_category
        self._add_character_dropdown()
        
        # Update embed to show current category
        embed = discord.Embed(
            title="🚫 서번트 밴 단계",
            description=f"**현재 카테고리: {new_category}**\n"
                       "각 팀장은 밴하고 싶은 서번트를 **2명**씩 선택하세요.",
            color=INFO_COLOR
        )
        
        # Show characters in current category
        chars_in_category = self.draft.servant_categories[new_category]
        char_list = "\n".join([f"• {char}" for char in chars_in_category])
        embed.add_field(name=f"{new_category} 서번트 목록", value=char_list, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)


class BanCategoryButton(discord.ui.Button):
    """Button for selecting servant category for banning"""
    
    def __init__(self, category: str, index: int):
        # Use different colors for different categories
        colors = [
            discord.ButtonStyle.primary,   # Blue
            discord.ButtonStyle.secondary, # Gray
            discord.ButtonStyle.success,   # Green
            discord.ButtonStyle.danger,    # Red
        ]
        
        super().__init__(
            label=category,
            style=colors[index % len(colors)],
            custom_id=f"ban_category_{category}"
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category button click"""
        view: ServantBanView = self.view
        await view.update_category(self.category, interaction)


class BanCharacterDropdown(discord.ui.Select):
    """Dropdown for selecting characters to ban"""
    
    def __init__(self, draft: DraftSession, bot_commands: 'TeamDraftCommands', characters: List[str], category: str):
        self.draft = draft
        self.bot_commands = bot_commands
        self.category = category
        
        # Create options for available characters in this category
        options = [
            discord.SelectOption(label=char, value=char, description=f"{category} 클래스")
            for char in characters[:25]  # Discord limit
        ]
        
        super().__init__(
            placeholder=f"{category} 서번트를 밴하세요...",
            options=options,
            min_values=1,
            max_values=min(2, len(options))  # Allow up to 2 selections, but not more than available
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle character ban selection"""
        user_id = interaction.user.id
        
        # Check if user is a captain
        if user_id not in self.draft.captains:
            await interaction.response.send_message(
                "팀장만 서번트를 밴할 수 있습니다.", ephemeral=True
            )
            return
        
        # Check if captain already submitted bans
        if user_id in self.draft.bans_submitted:
            await interaction.response.send_message(
                "이미 밴을 제출했습니다.", ephemeral=True
            )
            return
        
        selected_characters = self.values
        
        # Store the captain's bans
        self.draft.captain_bans[user_id] = selected_characters
        self.draft.bans_submitted.add(user_id)
        
        captain_name = self.draft.players[user_id].username
        ban_list = ", ".join(selected_characters)
        
        await interaction.response.send_message(
            f"**{captain_name}**이(가) **{ban_list}**을(를) 밴했습니다!", 
            ephemeral=True
        )
        
        # Check if both captains have submitted bans
        if len(self.draft.bans_submitted) == 2:
            await self.bot_commands._complete_servant_bans(self.draft) 