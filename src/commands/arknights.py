import discord
from discord import app_commands
from discord.ext import commands
from src.commands.base_commands import BaseCommands
from src.services.gacha.arknights import ArknightsGachaCalculator
from src.utils.constants import INFO_COLOR

class ArknightsCommands(BaseCommands):
    """Commands related to Arknights game"""

    def __init__(self) -> None:
        super().__init__()
        self.calculator = ArknightsGachaCalculator()

    @app_commands.command(
        name='arknights_pull',
        description='Calculate probability of getting the rate-up 6★ operator in Arknights'
    )
    @app_commands.describe(
        pulls='Number of pulls you plan to do'
    )
    async def arknights_pull_slash(
        self,
        interaction: discord.Interaction,
        pulls: int
    ) -> None:
        """Calculate Arknights pull probabilities"""
        await self._handle_pull_calc(interaction, pulls)

    @commands.command(name='명방')
    async def arknights_pull_prefix(
        self,
        ctx: commands.Context,
        pulls: int
    ) -> None:
        """Calculate Arknights pull probabilities
        
        Usage:
            뮤 명방 [pulls]
            Example: 뮤 명방 50
        """
        await self._handle_pull_calc(ctx, pulls)

    @commands.command(name='명방한정')
    async def arknights_limited_pull_prefix(
        self,
        ctx: commands.Context,
        pulls: int
    ) -> None:
        """Calculate Arknights limited banner pull probabilities
        
        Usage:
            뮤 명방한정 [pulls]
            Example: 뮤 명방한정 300
        """
        await self._handle_pull_calc(ctx, pulls, is_limited=True)

    @app_commands.command(
        name='arknights_resources',
        description='Calculate possible pulls from your Arknights resources'
    )
    @app_commands.describe(
        orundum='Amount of Orundum you have',
        originite='Amount of Originite Prime you have',
        permits='Number of Headhunting Permits you have'
    )
    async def resources_slash(
        self,
        interaction: discord.Interaction,
        orundum: int = 0,
        originite: int = 0,
        permits: int = 0
    ) -> None:
        """Calculate pulls from resources"""
        await self._handle_resource_calc(interaction, orundum, originite, permits)

    @commands.command(name='자원')
    async def resources_prefix(
        self,
        ctx: commands.Context,
        orundum: int = 0,
        originite: int = 0,
        permits: int = 0
    ) -> None:
        """Calculate pulls from Arknights resources
        
        Usage:
            뮤 자원 [합성옥] [순오리지늄] [헤드헌팅권]
            Example: 뮤 자원 6000 10 2
        """
        await self._handle_resource_calc(ctx, orundum, originite, permits)

    async def _handle_pull_calc(
        self,
        ctx_or_interaction: discord.Interaction | commands.Context,
        pulls: int,
        is_limited: bool = False
    ) -> None:
        """Handle pull calculation request"""
        try:
            # Validate input
            if pulls <= 0:
                await self.send_error(
                    ctx_or_interaction,
                    "뽑기 횟수는 1회 이상이어야 해.",
                    ephemeral=True
                )
                return

            if pulls > 1000:
                await self.send_error(
                    ctx_or_interaction,
                    "계산 가능한 최대 뽑기 횟수는 1000회야.",
                    ephemeral=True
                )
                return

            # Calculate probabilities
            result = self.calculator.calculate_banner_probability(pulls, is_limited)
            
            # Create embed
            user_name = self.get_user_name(ctx_or_interaction)
            embed = discord.Embed(
                title="🎲 명일방주 뽑기 확률 계산",
                description=f"{user_name}의 {pulls}회 뽑기 결과야.",
                color=INFO_COLOR
            )

            banner_rate = "35%" if is_limited else "50%"
            banner_type = "한정 픽업 배너" if is_limited else "일반 픽업 배너"
            
            embed.add_field(
                name="뽑기 정보",
                value=f"계획 뽑기 횟수: {pulls}회\n"
                      f"배너 종류: {banner_type} ({banner_rate} 확률)",
                inline=False
            )

            prob_percent = result['probability'] * 100
            expected_6stars = result['expected_6stars']
            expected_target = result['expected_target']

            embed.add_field(
                name="결과",
                value=f"픽업 오퍼레이터를 얻을 확률: {prob_percent:.1f}%\n"
                      f"예상 6성 획득 횟수: {expected_6stars:.1f}회\n"
                      f"예상 픽업 오퍼레이터 획득 횟수: {expected_target:.2f}회",
                inline=False
            )

            # Send response
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)

        except ValueError as e:
            error_msg = str(e)
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(
                    f"❌ {error_msg}",
                    ephemeral=True
                )
            else:
                await ctx_or_interaction.send(f"❌ {error_msg}")

    async def _handle_resource_calc(
        self,
        ctx_or_interaction: discord.Interaction | commands.Context,
        orundum: int = 0,
        originite: int = 0,
        permits: int = 0
    ) -> None:
        """Handle resource calculation request"""
        try:
            # Input validation
            if orundum < 0 or originite < 0 or permits < 0:
                raise ValueError("자원 수량은 0 이상이어야 해.")

            # Calculate pulls from resources
            result = self.calculator.calculate_pulls_from_resources(
                orundum=orundum,
                originite=originite,
                permits=permits
            )

            # Create response embed
            embed = discord.Embed(
                title="💎 명일방주 자원 계산기",
                description="보유 자원으로 가능한 뽑기 횟수 계산",
                color=INFO_COLOR
            )

            # Add resource info
            embed.add_field(
                name="보유 자원",
                value=f"합성옥: {orundum:,}\n"
                      f"순오리지늄: {originite:,}\n"
                      f"헤드헌팅권: {permits:,}장",
                inline=False
            )

            # Add pull calculations
            embed.add_field(
                name="가능한 뽑기 횟수",
                value=f"합성옥으로: {result['from_orundum']:,}회\n"
                      f"순오리지늄으로: {result['from_originite']:,}회\n"
                      f"헤드헌팅권으로: {result['from_permits']:,}회\n"
                      f"**총 가능한 뽑기: {result['total_pulls']:,}회**",
                inline=False
            )

            # Calculate probability with total pulls
            if result['total_pulls'] > 0:
                prob_result = self.calculator.calculate_banner_probability(result['total_pulls'])
                prob_percent = prob_result['probability'] * 100
                expected_6stars = prob_result['expected_6stars']
                expected_target = prob_result['expected_target']

                embed.add_field(
                    name="확률 예측",
                    value=f"픽업 오퍼레이터를 얻을 확률: {prob_percent:.1f}%\n"
                          f"예상 6성 획득 횟수: {expected_6stars:.1f}회\n"
                          f"예상 픽업 오퍼레이터 획득 횟수: {expected_target:.2f}회",
                    inline=False
                )

            # Send response
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)

        except ValueError as e:
            error_msg = str(e)
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(
                    f"❌ {error_msg}",
                    ephemeral=True
                )
            else:
                await ctx_or_interaction.send(f"❌ {error_msg}") 