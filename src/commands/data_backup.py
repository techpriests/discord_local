"""
Data Backup Commands

Owner-only commands for backing up and retrieving bot data.
Allows safe data retrieval before system updates or migrations.
"""

import discord
from discord.ext import commands
import json
import os
import zipfile
import io
from pathlib import Path
from typing import Optional, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DataBackupCommands(commands.Cog):
    """Commands for backing up bot data"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data_dir = Path(os.getenv("MUMU_DATA_DIR", "data"))
    
    # Removed manual owner check - using @commands.is_owner() decorator instead
    
    async def _create_data_backup(self) -> io.BytesIO:
        """Create a ZIP backup of all bot data"""
        backup_buffer = io.BytesIO()
        
        with zipfile.ZipFile(backup_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add timestamp info
            backup_info = {
                "created_at": datetime.now().isoformat(),
                "backup_type": "full_data_backup",
                "bot_version": "team_draft_refactor_v2"
            }
            zip_file.writestr("backup_info.json", json.dumps(backup_info, indent=2))
            
            # Backup roster data
            roster_dir = self.data_dir / "rosters"
            if roster_dir.exists():
                for roster_file in roster_dir.glob("*.json"):
                    with open(roster_file, 'r', encoding='utf-8') as f:
                        zip_file.writestr(f"rosters/{roster_file.name}", f.read())
            
            # Backup match records
            records_file = self.data_dir / "drafts" / "records.jsonl"
            if records_file.exists():
                with open(records_file, 'r', encoding='utf-8') as f:
                    zip_file.writestr("drafts/records.jsonl", f.read())
            
            # Backup API usage data
            for api_file in ["memory.json", "claude_memory.json"]:
                api_path = self.data_dir / api_file
                if api_path.exists():
                    with open(api_path, 'r', encoding='utf-8') as f:
                        zip_file.writestr(api_file, f.read())
            
            # Add any other data files
            for json_file in self.data_dir.glob("*.json"):
                if json_file.name not in ["memory.json", "claude_memory.json"]:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        zip_file.writestr(json_file.name, f.read())
        
        backup_buffer.seek(0)
        return backup_buffer
    
    def _get_data_summary(self) -> str:
        """Get summary of available data"""
        summary_lines = ["📊 **Bot Data Summary**\n"]
        
        # Check rosters
        roster_dir = self.data_dir / "rosters"
        if roster_dir.exists():
            roster_files = list(roster_dir.glob("*.json"))
            summary_lines.append(f"🧑‍💼 **Rosters**: {len(roster_files)} guild(s)")
            for roster_file in roster_files:
                try:
                    with open(roster_file, 'r') as f:
                        data = json.load(f)
                        player_count = len(data.get("players", []))
                        guild_id = roster_file.stem
                        summary_lines.append(f"  • Guild {guild_id}: {player_count} players")
                except Exception:
                    summary_lines.append(f"  • {roster_file.name}: Error reading")
        else:
            summary_lines.append("🧑‍💼 **Rosters**: No data found")
        
        # Check match records
        records_file = self.data_dir / "drafts" / "records.jsonl"
        if records_file.exists():
            try:
                with open(records_file, 'r') as f:
                    lines = f.readlines()
                    summary_lines.append(f"🎮 **Match Records**: {len(lines)} entries")
            except Exception:
                summary_lines.append("🎮 **Match Records**: Error reading")
        else:
            summary_lines.append("🎮 **Match Records**: No data found")
        
        # Check API usage
        for api_name, filename in [("Gemini", "memory.json"), ("Claude", "claude_memory.json")]:
            api_file = self.data_dir / filename
            if api_file.exists():
                try:
                    with open(api_file, 'r') as f:
                        data = json.load(f)
                        requests = data.get("daily_requests", 0)
                        summary_lines.append(f"🤖 **{api_name} API**: {requests} requests tracked")
                except Exception:
                    summary_lines.append(f"🤖 **{api_name} API**: Error reading")
        
        return "\n".join(summary_lines)
    
    @commands.command(name="데이터백업", hidden=True)
    @commands.is_owner()
    async def backup_data(self, ctx: commands.Context) -> None:
        """
        **Owner Only**: Create and upload complete data backup
        
        Creates a ZIP file containing:
        - All roster data (player ratings, stats)
        - All match history records
        - API usage tracking data
        """
        
        try:
            # Send initial message
            msg = await ctx.send("🔄 Creating data backup...")
            
            # Create backup
            backup_zip = await self._create_data_backup()
            
            # Prepare file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mumu_bot_data_backup_{timestamp}.zip"
            
            backup_file = discord.File(backup_zip, filename=filename)
            
            # Create embed with summary
            embed = discord.Embed(
                title="📦 Data Backup Complete",
                description="Complete backup of all bot data",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="📁 Backup Contents",
                value="• Player rosters (all guilds)\n• Match history records\n• API usage data\n• System metadata",
                inline=False
            )
            
            embed.add_field(
                name="📋 Data Summary", 
                value=self._get_data_summary(),
                inline=False
            )
            
            embed.add_field(
                name="⚠️ Important",
                value="Save this file safely before any system updates!\n"
                      "Use `데이터복원` to restore if needed.",
                inline=False
            )
            
            # Upload backup
            await msg.edit(content="✅ Backup ready!", embed=embed)
            await ctx.send(file=backup_file)
            
            logger.info(f"Data backup created and uploaded by {ctx.author.id}")
            
        except Exception as e:
            logger.error(f"Data backup failed: {e}")
            await ctx.send(f"❌ Backup failed: {str(e)}")
    
    @commands.command(name="데이터요약", hidden=True)
    @commands.is_owner()
    async def data_summary(self, ctx: commands.Context) -> None:
        """
        **Owner Only**: Show summary of current data without backup
        """
        
        try:
            summary = self._get_data_summary()
            
            embed = discord.Embed(
                title="📊 Current Data Status",
                description=summary,
                color=0x3498db,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="💾 Data Location",
                value=f"Server path: `{self.data_dir.absolute()}`",
                inline=False
            )
            
            embed.add_field(
                name="🛠️ Available Commands", 
                value="`데이터백업` - Create full backup ZIP\n"
                      "`데이터상세` - Show detailed file info",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Data summary failed: {e}")
            await ctx.send(f"❌ Failed to get data summary: {str(e)}")
    
    @commands.command(name="데이터상세", hidden=True)
    @commands.is_owner()
    async def detailed_data_info(self, ctx: commands.Context) -> None:
        """
        **Owner Only**: Show detailed information about each data file
        """
        
        try:
            info_lines = []
            
            # Detailed roster info
            roster_dir = self.data_dir / "rosters"
            if roster_dir.exists():
                info_lines.append("📁 **Roster Files:**")
                for roster_file in roster_dir.glob("*.json"):
                    try:
                        size = roster_file.stat().st_size
                        modified = datetime.fromtimestamp(roster_file.stat().st_mtime)
                        with open(roster_file, 'r') as f:
                            data = json.load(f)
                            players = data.get("players", [])
                        
                        info_lines.append(
                            f"  • `{roster_file.name}`: {len(players)} players, "
                            f"{size:,} bytes, modified {modified.strftime('%Y-%m-%d %H:%M')}"
                        )
                    except Exception as e:
                        info_lines.append(f"  • `{roster_file.name}`: Error - {e}")
            
            # Match records info
            records_file = self.data_dir / "drafts" / "records.jsonl"
            if records_file.exists():
                try:
                    size = records_file.stat().st_size
                    modified = datetime.fromtimestamp(records_file.stat().st_mtime)
                    with open(records_file, 'r') as f:
                        lines = f.readlines()
                    
                    info_lines.append("")
                    info_lines.append("🎮 **Match Records:**")
                    info_lines.append(
                        f"  • `records.jsonl`: {len(lines)} matches, "
                        f"{size:,} bytes, modified {modified.strftime('%Y-%m-%d %H:%M')}"
                    )
                except Exception as e:
                    info_lines.append(f"  • `records.jsonl`: Error - {e}")
            
            # API usage files
            for api_name, filename in [("Gemini", "memory.json"), ("Claude", "claude_memory.json")]:
                api_file = self.data_dir / filename
                if api_file.exists():
                    try:
                        size = api_file.stat().st_size
                        modified = datetime.fromtimestamp(api_file.stat().st_mtime)
                        
                        if not info_lines or not info_lines[-1].startswith("🤖"):
                            info_lines.append("")
                            info_lines.append("🤖 **API Usage:**")
                        
                        info_lines.append(
                            f"  • `{filename}`: {size:,} bytes, "
                            f"modified {modified.strftime('%Y-%m-%d %H:%M')}"
                        )
                    except Exception as e:
                        info_lines.append(f"  • `{filename}`: Error - {e}")
            
            if not info_lines:
                info_lines = ["No data files found."]
            
            # Split into multiple embeds if too long
            content = "\n".join(info_lines)
            
            if len(content) <= 4000:
                embed = discord.Embed(
                    title="📋 Detailed Data Information",
                    description=content,
                    color=0x9b59b6,
                    timestamp=datetime.now()
                )
                await ctx.send(embed=embed)
            else:
                # Split into multiple messages
                chunks = []
                current_chunk = []
                current_length = 0
                
                for line in info_lines:
                    if current_length + len(line) + 1 > 3900:  # Leave room for embed overhead
                        chunks.append("\n".join(current_chunk))
                        current_chunk = [line]
                        current_length = len(line)
                    else:
                        current_chunk.append(line)
                        current_length += len(line) + 1
                
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                
                for i, chunk in enumerate(chunks):
                    embed = discord.Embed(
                        title=f"📋 Detailed Data Information ({i+1}/{len(chunks)})",
                        description=chunk,
                        color=0x9b59b6,
                        timestamp=datetime.now()
                    )
                    await ctx.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Detailed data info failed: {e}")
            await ctx.send(f"❌ Failed to get detailed info: {str(e)}")


async def setup(bot: commands.Bot) -> None:
    """Setup function for the cog"""
    await bot.add_cog(DataBackupCommands(bot))
