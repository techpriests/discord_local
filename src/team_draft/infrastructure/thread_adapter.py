"""
Thread Service Adapter

Implements Discord thread creation and hybrid messaging functionality.
Preserves legacy thread behavior from the original system.
"""

import discord
import logging
import time
import re
from typing import Optional, List
from ..application.interfaces import IThreadService

logger = logging.getLogger(__name__)


class DiscordThreadAdapter(IThreadService):
    """
    Adapter for Discord thread operations.
    
    Preserves legacy thread creation and naming logic.
    """
    
    def __init__(self, bot: discord.ext.commands.Bot):
        self.bot = bot
    
    async def create_draft_thread(self, channel_id: int, thread_name: str, team_format: str, players: List[str]) -> Optional[int]:
        """Create thread for draft - preserves legacy naming and setup"""
        try:
            main_channel = self.bot.get_channel(channel_id)
            if not main_channel or not hasattr(main_channel, 'create_thread'):
                logger.warning(f"Cannot create thread in channel {channel_id}")
                return None
            
            # Generate unique thread name with numbering (legacy logic)
            base_name = f"팀 드래프트 ({team_format})"
            final_thread_name = f"🏆 {base_name}"
            
            # Check for existing threads and add numbering if needed
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
                        match = re.search(rf"{re.escape(base_name)} #(\d+)", thread.name)
                        if match:
                            existing_numbers.append(int(match.group(1)))
                        elif thread.name == f"🏆 {base_name}":
                            existing_numbers.append(1)  # Original thread is #1
                
                # Determine next available number
                if existing_numbers:
                    next_number = max(existing_numbers) + 1
                    final_thread_name = f"🏆 {base_name} #{next_number}"
                
            except Exception as e:
                logger.warning(f"Could not check existing threads for numbering: {e}")
                # Fallback to timestamp-based naming
                timestamp = int(time.time()) % 10000  # Last 4 digits
                final_thread_name = f"🏆 {base_name} #{timestamp}"
            
            # Create the thread
            thread = await main_channel.create_thread(
                name=final_thread_name,
                type=discord.ChannelType.public_thread,
                reason="Team draft session"
            )
            
            logger.info(f"Created draft thread {thread.id} in channel {channel_id}")
            
            # Send welcome message to thread
            welcome_embed = discord.Embed(
                title=f"🏆 팀 드래프트 시작! ({team_format})",
                description="이 스레드에서 드래프트가 진행될거야.\n"
                           "참가자들은 여기서 드래프트 인터페이스를 사용해줘.",
                color=0x3498db  # INFO_COLOR
            )
            
            if players:
                player_list = "\n".join([f"• {player}" for player in players])
                welcome_embed.add_field(name="참가자", value=player_list, inline=False)
            
            await thread.send(embed=welcome_embed)
            
            return thread.id
            
        except Exception as e:
            logger.error(f"Failed to create draft thread: {e}")
            return None
    
    async def send_to_thread_and_main(self, channel_id: int, thread_id: Optional[int], embed, view=None) -> None:
        """Send message to both thread and main channel - preserves legacy behavior"""
        try:
            # Send to thread first if available
            if thread_id:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    try:
                        await thread.send(embed=embed, view=view)
                    except Exception as e:
                        logger.warning(f"Failed to send to thread {thread_id}: {e}")
            
            # Send to main channel (simplified version for status updates)
            main_channel = self.bot.get_channel(channel_id)
            if main_channel and thread_id:  # Only send to main if in hybrid mode
                try:
                    # Create a simplified embed for main channel (no view)
                    main_embed = discord.Embed(
                        title=f"📊 {embed.title}" if embed.title else "📊 드래프트 진행 중",
                        description=embed.description or "스레드에서 드래프트가 진행되고 있어.",
                        color=embed.color or 0x3498db
                    )
                    
                    # Add link to thread
                    main_embed.add_field(
                        name="드래프트 스레드",
                        value=f"<#{thread_id}>에서 참가해줘!",
                        inline=False
                    )
                    
                    await main_channel.send(embed=main_embed)
                except Exception as e:
                    logger.warning(f"Failed to send to main channel {channel_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in send_to_thread_and_main: {e}")
    
    async def send_to_thread_with_fallback(self, channel_id: int, thread_id: Optional[int], embed, view=None) -> None:
        """Send message to thread if available, otherwise to main channel"""
        try:
            if thread_id:
                # Try thread first
                thread = self.bot.get_channel(thread_id)
                if thread:
                    try:
                        await thread.send(embed=embed, view=view)
                        return
                    except Exception as e:
                        logger.warning(f"Failed to send to thread {thread_id}: {e}")
            
            # Fallback to main channel
            main_channel = self.bot.get_channel(channel_id)
            if main_channel:
                await main_channel.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Error in send_to_thread_with_fallback: {e}")
    
    async def update_message_in_thread(self, channel_id: int, thread_id: Optional[int], message_id: int, embed, view=None) -> bool:
        """Update an existing message in thread or main channel"""
        try:
            # Try thread first if available
            if thread_id:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    try:
                        message = await thread.fetch_message(message_id)
                        await message.edit(embed=embed, view=view)
                        return True
                    except Exception as e:
                        logger.warning(f"Failed to update message in thread {thread_id}: {e}")
            
            # Fallback to main channel
            main_channel = self.bot.get_channel(channel_id)
            if main_channel:
                try:
                    message = await main_channel.fetch_message(message_id)
                    await message.edit(embed=embed, view=view)
                    return True
                except Exception as e:
                    logger.warning(f"Failed to update message in main channel {channel_id}: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"Error in update_message_in_thread: {e}")
            return False
