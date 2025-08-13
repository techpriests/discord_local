import asyncio
import hashlib
import logging
import os
from datetime import datetime
from typing import List, Optional, Tuple, Union

import discord
from discord.ext import commands
from discord import app_commands

from .base_commands import BaseCommands

logger = logging.getLogger(__name__)


class FateReplayCommands(BaseCommands):
    """Replay upload, storage, and retrieval for Fate (Warcraft 3)"""

    # Restrict to this channel (and its threads)
    RESTRICTED_CHANNEL_ID = 1395733550728216646

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot
        self.replay_base_dir = os.path.join("data", "replays", "fate")

    # ---------- Helpers ----------
    def _get_collection_channel_id(self, channel: Union[discord.TextChannel, discord.Thread]) -> int:
        if isinstance(channel, discord.Thread) and channel.parent:
            return channel.parent.id
        return channel.id

    def _is_allowed_channel(self, channel: Union[discord.TextChannel, discord.Thread]) -> bool:
        try:
            if isinstance(channel, discord.Thread) and channel.parent:
                return channel.parent.id == self.RESTRICTED_CHANNEL_ID
            return channel.id == self.RESTRICTED_CHANNEL_ID
        except Exception:
            return False

    def _get_channel_replay_dir(self, guild_id: Optional[int], collection_channel_id: int) -> str:
        guild_part = str(guild_id) if guild_id is not None else "dm"
        return os.path.join(self.replay_base_dir, guild_part, str(collection_channel_id))

    def _ensure_directory(self, directory_path: str) -> None:
        os.makedirs(directory_path, exist_ok=True)

    def _find_existing_replay_by_hash(self, directory_path: str, hash_prefix: str) -> Optional[str]:
        try:
            for filename in os.listdir(directory_path):
                if hash_prefix in filename and filename.lower().endswith(".w3g"):
                    return os.path.join(directory_path, filename)
        except FileNotFoundError:
            return None
        return None

    async def _store_replay_attachment(
        self,
        message: discord.Message,
        attachment: discord.Attachment,
        collection_channel_id: int
    ) -> Optional[Tuple[str, bool, str]]:
        try:
            # Basic size guard (Discord hard limit applies too)
            if attachment.size and attachment.size > 5 * 1024 * 1024:  # 5MB
                logger.warning("Replay too large to store: %s bytes", attachment.size)
                return None

            data: bytes = await attachment.read()
            file_hash = hashlib.sha1(data).hexdigest()
            hash_prefix = file_hash[:10]

            guild_id = message.guild.id if message.guild else None
            target_dir = self._get_channel_replay_dir(guild_id, collection_channel_id)
            self._ensure_directory(target_dir)

            # Deduplicate by hash
            existing = self._find_existing_replay_by_hash(target_dir, hash_prefix)
            if existing:
                return existing, True, hash_prefix

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{message.author.id}_{hash_prefix}.w3g"
            file_path = os.path.join(target_dir, filename)

            with open(file_path, "wb") as f:
                f.write(data)

            return file_path, False, hash_prefix
        except Exception as e:
            logger.error(f"Failed to store replay attachment: {e}")
            return None

    def _list_replay_files(self, directory_path: str) -> List[str]:
        try:
            files = [
                os.path.join(directory_path, name)
                for name in os.listdir(directory_path)
                if name.lower().endswith(".w3g")
            ]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return files
        except FileNotFoundError:
            return []

    # ---------- Events ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            if message.author.bot:
                return
            if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
                return
            if not self._is_allowed_channel(message.channel):
                return
            if not message.attachments:
                return

            collection_channel_id = self._get_collection_channel_id(message.channel)

            saved_any = False
            for attachment in message.attachments:
                name_lower = (attachment.filename or "").lower()
                if name_lower.endswith(".w3g") or "lastreplay" in name_lower:
                    result = await self._store_replay_attachment(message, attachment, collection_channel_id)
                    if result:
                        file_path, is_duplicate, hash_prefix = result
                        saved_any = True
                        note = "(중복, 기존 파일 참조)" if is_duplicate else ""
                        try:
                            await message.channel.send(
                                f"📥 Fate 리플 저장됨: `{os.path.basename(file_path)}` id:`{hash_prefix}` {note}"
                            )
                        except Exception:
                            pass

            if not saved_any:
                return
        except Exception as e:
            logger.error(f"Error handling replay upload message: {e}")

    # ---------- Commands (slash) ----------
    @app_commands.command(name="페어리플목록", description="이 채널의 최근 Fate 리플레이 목록을 보여줘")
    @app_commands.default_permissions(administrator=True)
    async def list_fate_replays(self, interaction: discord.Interaction, limit: int = 10) -> None:
        try:
            if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                await interaction.response.send_message("서버 채널에서만 사용할 수 있어.", ephemeral=True)
                return
            if not self._is_allowed_channel(interaction.channel):
                await interaction.response.send_message("이 기능은 지정된 채널에서만 사용 가능해.", ephemeral=True)
                return

            limit = max(1, min(limit, 20))
            collection_channel_id = self._get_collection_channel_id(interaction.channel)
            target_dir = self._get_channel_replay_dir(interaction.guild.id if interaction.guild else None, collection_channel_id)
            files = self._list_replay_files(target_dir)[:limit]
            if not files:
                await interaction.response.send_message("이 채널에 저장된 리플이 없어.", ephemeral=True)
                return

            lines = []
            for idx, path in enumerate(files, start=1):
                base = os.path.basename(path)
                size_kb = os.path.getsize(path) // 1024
                lines.append(f"{idx}. {base} ({size_kb}KB)")

            await interaction.response.send_message("\n".join(lines), ephemeral=True)
        except Exception as e:
            logger.error(f"Error listing replays: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("리플 목록을 가져오는데 실패했어.", ephemeral=True)
            else:
                await interaction.followup.send("리플 목록을 가져오는데 실패했어.", ephemeral=True)

    @app_commands.command(name="페어리플다운", description="최근 N번째 또는 id로 Fate 리플을 내려줘")
    @app_commands.default_permissions(administrator=True)
    async def download_fate_replay(
        self,
        interaction: discord.Interaction,
        index: int = 1,
        id: str = ""
    ) -> None:
        try:
            if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                await interaction.response.send_message("서버 채널에서만 사용할 수 있어.", ephemeral=True)
                return
            if not self._is_allowed_channel(interaction.channel):
                await interaction.response.send_message("이 기능은 지정된 채널에서만 사용 가능해.", ephemeral=True)
                return

            collection_channel_id = self._get_collection_channel_id(interaction.channel)
            target_dir = self._get_channel_replay_dir(interaction.guild.id if interaction.guild else None, collection_channel_id)
            files = self._list_replay_files(target_dir)
            if not files:
                await interaction.response.send_message("이 채널에 저장된 리플이 없어.", ephemeral=True)
                return

            chosen_path: Optional[str] = None
            if id:
                id_lower = id.strip().lower()
                for path in files:
                    if id_lower in os.path.basename(path).lower():
                        chosen_path = path
                        break
                if not chosen_path:
                    await interaction.response.send_message("해당 id의 리플을 찾을 수 없어.", ephemeral=True)
                    return
            else:
                index = max(1, min(index, len(files)))
                chosen_path = files[index - 1]

            if not chosen_path or not os.path.exists(chosen_path):
                await interaction.response.send_message("리플 파일을 찾을 수 없어.", ephemeral=True)
                return

            file = discord.File(chosen_path, filename=os.path.basename(chosen_path))
            await interaction.response.send_message(content="📤 리플 파일: ", file=file, ephemeral=True)
        except Exception as e:
            logger.error(f"Error sending replay: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("리플 전송에 실패했어.", ephemeral=True)
            else:
                await interaction.followup.send("리플 전송에 실패했어.", ephemeral=True)

    # ---------- Commands (text) ----------
    @commands.command(name="페어리플목록", help="이 채널의 최근 Fate 리플 목록을 보여줘", aliases=["fate_replays"], hidden=False)
    @commands.has_permissions(administrator=True)
    async def list_fate_replays_text(self, ctx: commands.Context, limit: int = 10) -> None:
        try:
            if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
                await ctx.send("서버 채널에서만 사용할 수 있어.")
                return
            if not self._is_allowed_channel(ctx.channel):
                await ctx.send("이 기능은 지정된 채널에서만 사용 가능해.")
                return
            limit = max(1, min(limit, 20))
            collection_channel_id = self._get_collection_channel_id(ctx.channel)
            target_dir = self._get_channel_replay_dir(ctx.guild.id if ctx.guild else None, collection_channel_id)
            files = self._list_replay_files(target_dir)[:limit]
            if not files:
                await ctx.send("이 채널에 저장된 리플이 없어.")
                return
            lines = []
            for idx, path in enumerate(files, start=1):
                base = os.path.basename(path)
                size_kb = os.path.getsize(path) // 1024
                lines.append(f"{idx}. {base} ({size_kb}KB)")
            await ctx.send("\n".join(lines))
        except Exception as e:
            logger.error(f"Error listing replays (text): {e}")
            await ctx.send("리플 목록을 가져오는데 실패했어.")

    @commands.command(name="페어리플다운", help="최근 N번째 또는 id로 Fate 리플을 내려줘", aliases=["fate_replay"], hidden=False)
    @commands.has_permissions(administrator=True)
    async def download_fate_replay_text(self, ctx: commands.Context, index: int = 1, id: str = "") -> None:
        try:
            if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
                await ctx.send("서버 채널에서만 사용할 수 있어.")
                return
            if not self._is_allowed_channel(ctx.channel):
                await ctx.send("이 기능은 지정된 채널에서만 사용 가능해.")
                return
            collection_channel_id = self._get_collection_channel_id(ctx.channel)
            target_dir = self._get_channel_replay_dir(ctx.guild.id if ctx.guild else None, collection_channel_id)
            files = self._list_replay_files(target_dir)
            if not files:
                await ctx.send("이 채널에 저장된 리플이 없어.")
                return
            chosen_path: Optional[str] = None
            if id:
                id_lower = id.strip().lower()
                for path in files:
                    if id_lower in os.path.basename(path).lower():
                        chosen_path = path
                        break
                if not chosen_path:
                    await ctx.send("해당 id의 리플을 찾을 수 없어.")
                    return
            else:
                index = max(1, min(index, len(files)))
                chosen_path = files[index - 1]
            if not chosen_path or not os.path.exists(chosen_path):
                await ctx.send("리플 파일을 찾을 수 없어.")
                return
            await ctx.send(file=discord.File(chosen_path, filename=os.path.basename(chosen_path)))
        except Exception as e:
            logger.error(f"Error sending replay (text): {e}")
            await ctx.send("리플 전송에 실패했어.")


