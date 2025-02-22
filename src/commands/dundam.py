import discord
from discord.ext import commands
from discord import app_commands
import logging
import urllib.parse

from ..services.api.service import APIService

logger = logging.getLogger(__name__)

class DNFCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, api: APIService):
        self.bot = bot
        self.api = api

    @commands.hybrid_command(
        name="던파",
        aliases=["dnf", "df"],
        description="던전앤파이터 캐릭터의 정보를 검색합니다"
    )
    @app_commands.describe(
        character_name="검색할 캐릭터 이름",
        server_name="서버 이름 (예: 카인, 디레지에 등)"
    )
    async def search_dnf(
        self,
        ctx: commands.Context,
        character_name: str,
        server_name: str = "all"
    ) -> None:
        """던전앤파이터 캐릭터의 정보를 검색합니다"""
        
        # Send disabled message
        disabled_embed = discord.Embed(
            title="⚠️ 기능 비활성화",
            description=(
                "던전앤파이터 캐릭터 검색 기능이 현재 비활성화되어 있습니다.\n"
                "더 정확한 데미지 계산을 위해 업데이트 중입니다.\n"
                "추후 업데이트를 통해 다시 제공될 예정입니다."
            ),
            color=discord.Color.orange()
        )
        disabled_embed.add_field(
            name="대체 방법",
            value=(
                "캐릭터 정보 확인은 아래 사이트를 이용해주세요:\n"
                "• [던담](https://dundam.xyz/)\n"
                "• [네오플 던전앤파이터](https://df.nexon.com/)"
            ),
            inline=False
        )
        await ctx.send(embed=disabled_embed)

    @commands.hybrid_command(
        name="던파",
        aliases=["dnf", "df"],
        description="던전앤파이터 캐릭터의 정보를 검색합니다"
    )
    @app_commands.describe(
        character_name="검색할 캐릭터 이름",
        server_name="서버 이름 (예: 카인, 디레지에 등)"
    )
    async def search_dnf(
        self,
        ctx: commands.Context,
        character_name: str,
        server_name: str = "all"
    ) -> None:
        """던전앤파이터 캐릭터의 정보를 검색합니다"""
        
        # Send initial response
        loading_embed = discord.Embed(
            title="🔍 검색 중...",
            description=f"'{server_name}' 서버에서 '{character_name}' 캐릭터를 검색 중입니다.",
            color=discord.Color.blue()
        )
        message = await ctx.send(embed=loading_embed)
        
        try:
            # Search for character
            result = await self.api.dnf.search_character(character_name, server_name)
            
            if not result:
                error_embed = discord.Embed(
                    title="❌ 검색 실패",
                    description=f"'{server_name}' 서버에서 '{character_name}' 캐릭터를 찾을 수 없습니다.",
                    color=discord.Color.red()
                )
                error_embed.add_field(
                    name="도움말",
                    value=(
                        "1. 캐릭터 이름과 서버 이름을 정확히 입력했는지 확인해주세요.\n"
                        "2. 서버 이름은 '카인', '디레지에', '시로코' 등으로 입력해주세요.\n"
                        "3. 캐릭터가 최근에 생성되었다면 잠시 후 다시 시도해주세요."
                    ),
                    inline=False
                )
                await message.edit(embed=error_embed)
                return
            
            # Create success embed
            success_embed = discord.Embed(
                title=f"🎮 {result['name']} ({result['server']})",
                description=(
                    f"**직업:** {result.get('job_name', '알 수 없음')}\n"
                    f"**전직:** {result.get('job_growth_name', '알 수 없음')}\n"
                    f"**레벨:** {result['level']}\n"
                    f"**스탯:**\n"
                    f"- 힘: {result.get('stats', {}).get('str', '알 수 없음')}\n"
                    f"- 지능: {result.get('stats', {}).get('int', '알 수 없음')}\n"
                    f"- 체력: {result.get('stats', {}).get('vit', '알 수 없음')}\n"
                    f"- 정신력: {result.get('stats', {}).get('spr', '알 수 없음')}\n"
                    f"**버프력:** {result.get('buff_power', '알 수 없음')}\n"
                    f"**딜량:** {result.get('damage', '계산 중...')}"
                ),
                color=discord.Color.green()
            )
            
            # Add equipment info if available
            if result.get('equipment'):
                equip_text = ""
                for equip in result['equipment']:
                    equip_text += f"- {equip.get('name', '알 수 없음')} ({equip.get('rarity', '일반')})\n"
                success_embed.add_field(
                    name="장비",
                    value=equip_text or "장비 정보 없음",
                    inline=False
                )
            
            # Add footer with search info
            success_embed.set_footer(text=f"서버: {server_name} • 캐릭터: {character_name}")
            
            await message.edit(embed=success_embed)
            
        except Exception as e:
            logger.error(f"Error searching DNF character: {e}")
            error_embed = discord.Embed(
                title="⚠️ 오류 발생",
                description=(
                    "캐릭터 검색 중 오류가 발생했습니다.\n"
                    "잠시 후 다시 시도해주세요.\n"
                    f"오류 내용: {str(e)}"
                ),
                color=discord.Color.red()
            )
            await message.edit(embed=error_embed) 