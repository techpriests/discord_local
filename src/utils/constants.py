"""Constants used throughout the application"""

import discord

# Colors for embeds
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
INFO_COLOR = discord.Color.blue()

# Command cooldowns (in seconds)
DEFAULT_COOLDOWN = 3
STEAM_COOLDOWN = 3
POPULATION_COOLDOWN = 3

# API rate limits
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

# Message timeouts
DELETE_DELAY = 5  # seconds for temporary messages 