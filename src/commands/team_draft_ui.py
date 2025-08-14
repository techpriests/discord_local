"""
Discord UI components for team draft system.
Contains all Views, Buttons, Modals, and Select components.
"""

import logging
import time
import random
import asyncio
from typing import List, Optional, TYPE_CHECKING

import discord
from discord.ext import commands

from src.utils.constants import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR

if TYPE_CHECKING:
    from .team_draft import TeamDraftCommands, DraftSession, Player

logger = logging.getLogger(__name__)

# This file will contain all the UI components that were previously mixed with command methods
# For now, this is a placeholder - we'll move the UI classes here systematically
