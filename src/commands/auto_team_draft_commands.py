import logging
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.commands.base_commands import BaseCommands
from src.services.auto_team_draft import AutoTeamDraftService, PlayerInput
from src.utils.constants import INFO_COLOR, ERROR_COLOR


logger = logging.getLogger(__name__)


class AutoTeamDraftCommands(BaseCommands):
    """Commands to run automatic team draft in a channel.

    This module is independent from the existing interactive draft flow
    in `team_draft.py`. It provides a quick command to auto-assign teams
    given a list of users. It can be used alongside or instead of the
    interactive flow.
    """

    def __init__(self, bot: Optional[commands.Bot] = None) -> None:
        super().__init__()
        self.bot = bot
        self.service = AutoTeamDraftService()

    @commands.command(
        name="오토드래프트",
        help="현재 채널의 멤버 또는 멘션된 사용자로 자동 팀을 구성합니다 (기본 6v6).",
        aliases=["자동드래프트", "auto_draft"],
    )
    async def auto_draft_prefix(
        self,
        ctx: commands.Context,
        team_size: Optional[int] = 6,
    ) -> None:
        try:
            await self._handle_auto_draft(ctx, team_size)
        except Exception as e:
            logger.error(f"auto_draft_prefix failed: {e}")
            await self.send_error(ctx, "자동 드래프트 중 문제가 발생했어")

    @app_commands.command(name="auto_draft", description="자동 팀 드래프트를 실행합니다")
    async def auto_draft_slash(
        self,
        interaction: discord.Interaction,
        team_size: Optional[int] = 6,
    ) -> None:
        try:
            await self._handle_auto_draft(interaction, team_size)
        except Exception as e:
            logger.error(f"auto_draft_slash failed: {e}")
            await self.send_error(interaction, "자동 드래프트 중 문제가 발생했어")

    async def _handle_auto_draft(
        self,
        ctx_or_interaction: discord.Interaction | commands.Context,
        team_size: Optional[int],
    ) -> None:
        if not team_size:
            team_size = 6

        if team_size <= 0:
            await self.send_error(ctx_or_interaction, "팀 인원은 1명 이상이어야 해")
            return

        # Collect candidate users: prefer mentions if present, otherwise channel members
        members = await self._collect_members(ctx_or_interaction)
        if len(members) < 2:
            await self.send_error(ctx_or_interaction, "드래프트를 진행할 사람이 부족해")
            return

        # Map to PlayerInput with optional rating (None by default)
        players: List[PlayerInput] = [
            PlayerInput(user_id=m.id, display_name=m.display_name)
            for m in members
            if not m.bot
        ]

        if len(players) < 2:
            await self.send_error(ctx_or_interaction, "실제 플레이어가 부족해")
            return

        result = self.service.assign_teams(players, team_size, balance_by_rating=True)

        embed = discord.Embed(
            title="⚖️ 자동 팀 드래프트 결과",
            color=INFO_COLOR,
        )
        embed.add_field(
            name=f"팀 1 ({len(result.team_one)}명)",
            value="\n".join(p.display_name for p in result.team_one) or "없음",
            inline=True,
        )
        embed.add_field(
            name=f"팀 2 ({len(result.team_two)}명)",
            value="\n".join(p.display_name for p in result.team_two) or "없음",
            inline=True,
        )
        if result.extras:
            embed.add_field(
                name=f"대기 ({len(result.extras)}명)",
                value="\n".join(p.display_name for p in result.extras),
                inline=False,
            )

        await self.send_response(ctx_or_interaction, embed=embed)

    async def _collect_members(
        self, ctx_or_interaction: discord.Interaction | commands.Context
    ):
        # Mentions preferred in prefix usage
        if isinstance(ctx_or_interaction, commands.Context):
            mentions = ctx_or_interaction.message.mentions
            if mentions:
                return mentions
            if isinstance(ctx_or_interaction.channel, discord.TextChannel):
                return ctx_or_interaction.channel.members
            return []

        # Slash: use channel.guild members if possible
        guild = ctx_or_interaction.guild
        channel = ctx_or_interaction.channel
        if isinstance(channel, discord.TextChannel):
            return channel.members
        if guild is not None:
            return guild.members
        return []


