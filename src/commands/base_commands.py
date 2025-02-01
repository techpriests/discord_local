class BaseCommands(commands.Cog):
    async def send_response(self, ctx_or_interaction, content=None, *, embed=None):
        """Unified method to send responses"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            if embed:
                await ctx_or_interaction.channel.send(embed=embed)
            else:
                await ctx_or_interaction.channel.send(content)
        else:
            if embed:
                await ctx_or_interaction.send(embed=embed)
            else:
                await ctx_or_interaction.send(content) 