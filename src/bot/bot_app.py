from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..adapters.dayz_lists import DayZListAdapter, ServerLists
from ..core.audit import AuditEvent, AuditLogger
from ..core.config import AppConfig, ConfigLoader
from ..core.persistence import CursorRepository, UserRecord, UsersDatabase, UsersRepository
from ..core.server_policy import ServerPolicy
from ..watchers.ljson_tailer import LjsonTailer, parse_death_event


class SteamValidator:
    def validate(self, steam_id: str) -> bool:
        return steam_id.isdigit() and len(steam_id) >= 16


@dataclass
class ActiveTimer:
    expires_at: datetime


class DeathWatcherBot(commands.Bot):
    def __init__(self, config_path: Path) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
        self.config_loader = ConfigLoader(config_path)
        self.config = self.config_loader.load()
        self.audit = AuditLogger(Path(self.config.paths.audit_log_path))
        self.users_repo = UsersRepository(Path(self.config.paths.users_db_path))
        self.cursor_repo = CursorRepository(Path(self.config.paths.cursor_cache_path))
        self.users_db = self.users_repo.load()
        self.cursor_map = self.cursor_repo.load()
        self.policy = ServerPolicy(self.config.policy)
        self.validator = SteamValidator()
        self.timers: Dict[str, ActiveTimer] = {}
        self.tailers = {
            server.server_id: LjsonTailer(Path(server.path_to_logs_directory), self.cursor_map.get(server.server_id, 0))
            for server in self.config.servers
        }

    async def setup_hook(self) -> None:
        self.tree.add_command(self.validatesteamid)
        self.tree.add_command(self.setserver)
        self.tree.add_command(self.revive)
        self.tree.add_command(self.ban)
        self.tree.add_command(self.unban)
        self.tree.add_command(self.wipe)
        await self.tree.sync(guild=discord.Object(id=self.config.discord.guild_id))

    async def on_ready(self) -> None:
        self.audit.write(AuditEvent(event="bot_ready", message="Bot connected", context={}))

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if not self.config.features.enable_voice_enforcement:
            return
        if not after.channel and not before.channel:
            return
        guild = member.guild
        join_vc_id = self.config.discord.join_vc_id
        category_id = self.config.discord.join_vc_category_id
        user_record = self._get_user_by_discord_id(str(member.id))
        if not user_record or user_record.dead:
            return
        if after.channel and after.channel.id == join_vc_id:
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                return
            channel = discord.utils.get(category.voice_channels, name=str(member.id))
            if channel is None:
                channel = await guild.create_voice_channel(name=str(member.id), category=category)
            await member.move_to(channel)
            await self._apply_unban_for_user(user_record)
        elif before.channel and before.channel.name == str(member.id) and after.channel is None:
            await self._apply_ban_for_user(user_record)
            if before.channel and len(before.channel.members) == 0:
                await before.channel.delete()

    async def _apply_unban_for_user(self, user: UserRecord) -> None:
        server_ids = [server.server_id for server in self.config.servers]
        targets = self.policy.resolve_active_servers(user, server_ids)
        for server in self.config.servers:
            if server.server_id in targets:
                adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
                adapter.remove_from_ban(user.steam_id)
        await self._audit_discord("unban", user)

    async def _apply_ban_for_user(self, user: UserRecord) -> None:
        server_ids = [server.server_id for server in self.config.servers]
        targets = self.policy.resolve_active_servers(user, server_ids)
        for server in self.config.servers:
            if server.server_id in targets:
                adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
                adapter.add_to_ban(user.steam_id)
        await self._audit_discord("ban", user)

    async def _audit_discord(self, action: str, user: UserRecord) -> None:
        self.audit.write(
            AuditEvent(
                event=action,
                message=f"{action} applied",
                context={"steam_id": user.steam_id, "discord_id": user.discord_id},
            )
        )
        channel = self.get_channel(self.config.discord.dump_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(f"{action.title()} applied for {user.steam_id}")

    def _get_user_by_discord_id(self, discord_id: str) -> Optional[UserRecord]:
        for user in self.users_db.users.values():
            if user.discord_id == discord_id:
                return user
        return None

    async def poll_logs(self) -> None:
        if not self.config.features.enable_deathwatcher:
            return
        for server in self.config.servers:
            tailer = self.tailers[server.server_id]
            for event in tailer.read_events(server.server_id) or []:
                parsed = parse_death_event(event)
                if not parsed:
                    continue
                steam_id = parsed["steam_id"]
                user = self.users_db.users.get(steam_id, UserRecord(steam_id=steam_id))
                user.dead = True
                user.last_alive_sec = parsed.get("alive_sec")
                user.death_count += 1
                self.users_db.users[steam_id] = user
                adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
                adapter.add_to_ban(steam_id)
                self._start_timer(steam_id)
                self.users_repo.save(self.users_db)
                self.cursor_map[server.server_id] = tailer.cursor
                self.cursor_repo.save(self.cursor_map)
                self.audit.write(
                    AuditEvent(
                        event="death_detected",
                        message="Player death detected",
                        context={"steam_id": steam_id, "server_id": server.server_id},
                    )
                )

    def _start_timer(self, steam_id: str) -> None:
        duration = timedelta(minutes=self.config.ban_duration_minutes)
        self.timers[steam_id] = ActiveTimer(expires_at=datetime.now(timezone.utc) + duration)

    async def process_timers(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [steam_id for steam_id, timer in self.timers.items() if timer.expires_at <= now]
        for steam_id in expired:
            user = self.users_db.users.get(steam_id)
            if user:
                user.dead = False
                self.users_repo.save(self.users_db)
                await self._apply_unban_for_user(user)
            self.timers.pop(steam_id, None)

    @app_commands.command(name="validatesteamid", description="Validate a Steam64 ID")
    async def validatesteamid(self, interaction: discord.Interaction, steam64: str) -> None:
        if not self.validator.validate(steam64):
            await interaction.response.send_message("Invalid Steam64 ID.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64, UserRecord(steam_id=steam64))
        user.discord_id = str(interaction.user.id)
        user.dead = False
        self.users_db.users[steam64] = user
        server_ids = [server.server_id for server in self.config.servers]
        for server in self.config.servers:
            adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
            if server.server_id in self.policy.resolve_whitelist_targets(user, server_ids):
                adapter.add_to_whitelist(steam64)
            adapter.add_to_ban(steam64)
        self.users_repo.save(self.users_db)
        await interaction.response.send_message("Validated and added to lists.", ephemeral=True)

    @app_commands.command(name="setserver", description="Set active server ID for your account")
    async def setserver(self, interaction: discord.Interaction, server_id: str) -> None:
        user = self._get_user_by_discord_id(str(interaction.user.id))
        if not user:
            await interaction.response.send_message("User not validated.", ephemeral=True)
            return
        user.active_server_id = server_id
        self.users_repo.save(self.users_db)
        await interaction.response.send_message(f"Active server set to {server_id}.", ephemeral=True)

    @app_commands.command(name="revive", description="Admin revive a user by Steam64")
    async def revive(self, interaction: discord.Interaction, steam64: str) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64)
        if not user:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return
        user.dead = False
        self.users_repo.save(self.users_db)
        await self._apply_unban_for_user(user)
        await interaction.response.send_message("User revived.", ephemeral=True)

    @app_commands.command(name="ban", description="Admin ban a user by Steam64")
    async def ban(self, interaction: discord.Interaction, steam64: str) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64, UserRecord(steam_id=steam64))
        user.dead = True
        self.users_db.users[steam64] = user
        self.users_repo.save(self.users_db)
        await self._apply_ban_for_user(user)
        await interaction.response.send_message("User banned.", ephemeral=True)

    @app_commands.command(name="unban", description="Admin unban a user by Steam64")
    async def unban(self, interaction: discord.Interaction, steam64: str) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64)
        if not user:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return
        user.dead = False
        self.users_repo.save(self.users_db)
        await self._apply_unban_for_user(user)
        await interaction.response.send_message("User unbanned.", ephemeral=True)

    @app_commands.command(name="wipe", description="Admin wipe all user data")
    async def wipe(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        self.users_db = UsersDatabase()
        self.users_repo.save(self.users_db)
        await interaction.response.send_message("Database wiped.", ephemeral=True)
