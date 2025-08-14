"""
Roster management commands for the Discord bot.
Handles player roster operations like adding, removing, and updating player information.
"""

import discord
from discord.ext import commands
from typing import Optional

from src.services.roster_store import RosterStore, RosterPlayer
from src.commands.base_commands import BaseCommands


class RosterCommands(BaseCommands):
    """Commands for managing server roster"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.roster_store = RosterStore()
    
    @commands.command(name="로스터추가", help="서버 로스터에 플레이어를 추가/업데이트합니다 (owner-only)")
    @commands.is_owner()
    async def roster_add_prefix(self, ctx: commands.Context, member: discord.Member, rating: Optional[float] = None) -> None:
        guild_id = ctx.guild.id if ctx.guild else 0
        player = RosterPlayer(user_id=member.id, display_name=member.display_name, rating=rating)
        self.roster_store.add_or_update(guild_id, [player])
        await self.send_success(ctx, f"로스터에 {member.display_name}를 추가/업데이트했어")

    @commands.command(name="로스터삭제", help="서버 로스터에서 플레이어를 제거합니다 (owner-only)")
    @commands.is_owner()
    async def roster_remove_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        guild_id = ctx.guild.id if ctx.guild else 0
        self.roster_store.remove(guild_id, [member.id])
        await self.send_success(ctx, f"로스터에서 {member.display_name}를 제거했어")

    @commands.command(name="로스터서번트", help="특정 플레이어의 서번트 숙련도 점수를 설정합니다 (owner-only)")
    @commands.is_owner()
    async def roster_servant_prefix(self, ctx: commands.Context, member: discord.Member, servant: str, rating: Optional[float] = None) -> None:
        guild_id = ctx.guild.id if ctx.guild else 0
        self.roster_store.set_servant_rating(guild_id, member.id, servant, rating)
        await self.send_success(ctx, f"{member.display_name}의 {servant} 숙련도를 설정했어")

    @commands.command(name="로스터보기", help="서버 로스터를 표시합니다 (owner-only)")
    @commands.is_owner()
    async def roster_list_prefix(self, ctx: commands.Context) -> None:
        guild_id = ctx.guild.id if ctx.guild else 0
        roster = self.roster_store.load(guild_id)
        if not roster:
            await self.send_response(ctx, "로스터가 비어 있어")
            return
        lines = [f"• {p.display_name} ({p.user_id}) - rating: {p.rating if p.rating is not None else 'N/A'}" for p in roster]
        await self.send_response(ctx, "\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    """Load the cog"""
    await bot.add_cog(RosterCommands(bot))
