import discord
from discord.ext import commands
from discord import app_commands
import logging

from ..services.api.service import APIService

logger = logging.getLogger(__name__)

class DundamCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, api: APIService):
        self.bot = bot
        self.api = api

    @commands.hybrid_command(
        name="던담",
        aliases=["dundam", "df"],
        description="던전앤파이터 캐릭터의 총 데미지를 검색합니다"
    )
    @app_commands.describe(
        character_name="검색할 캐릭터 이름",
        server_name="서버 이름 (예: 카인, 디레지에 등)"
    )
    async def search_dundam(
        self,
        ctx: commands.Context,
        character_name: str,
        server_name: str = "all"
    ) -> None:
        """던담에서 캐릭터의 총 데미지를 검색합니다"""
        
        maintenance_embed = discord.Embed(
            title="🛠️ 기능 점검 중",
            description=(
                "던담 검색 기능이 일시적으로 비활성화되었습니다.\n"
                "더 나은 서비스를 위해 기능을 개선 중입니다.\n"
                "빠른 시일 내에 다시 찾아뵙겠습니다."
            ),
            color=discord.Color.orange()
        )
        maintenance_embed.add_field(
            name="대체 방법",
            value="[던담 웹사이트](https://dundam.xyz/)에서 직접 검색하실 수 있습니다.",
            inline=False
        )
        maintenance_embed.set_footer(text="기능이 다시 활성화되면 알려드리겠습니다.")
        
        await ctx.send(embed=maintenance_embed) 