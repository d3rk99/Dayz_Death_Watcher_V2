from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..adapters.dayz_lists import DayZListAdapter, ServerLists
from ..core.audit import AuditEvent, AuditLogger
from ..core.config import AppConfig, ConfigLoader
from ..core.error_reporting import ErrorReporter
from ..core.persistence import CursorRepository, UserRecord, UsersDatabase, UsersRepository
from ..core.server_policy import ServerPolicy
from ..watchers.ljson_tailer import LjsonTailer, TailerOptions, parse_death_event


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SteamValidatorInterface:
    async def validate(self, steam_id: str) -> bool:
        raise NotImplementedError


class SteamWebApiValidator(SteamValidatorInterface):
    def __init__(self, api_key: str, timeout_seconds: int = 6) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def validate(self, steam_id: str) -> bool:
        if not steam_id.isdigit() or len(steam_id) < 16:
            return False
        if not self.api_key:
            return False
        url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
        params = {"key": self.api_key, "steamids": steam_id}
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return False
                payload = await response.json()
        players = payload.get("response", {}).get("players", [])
        return any(player.get("steamid") == steam_id for player in players)


@dataclass
class PendingAction:
    label: str
    action: Callable[[], Awaitable[None]]


class ActionQueue:
    def __init__(self, delay_seconds: float = 0.4) -> None:
        self.queue: asyncio.Queue[PendingAction] = asyncio.Queue()
        self.delay_seconds = delay_seconds

    async def enqueue(self, label: str, action: Callable[[], Awaitable[None]]) -> None:
        await self.queue.put(PendingAction(label=label, action=action))

    async def run(self, bot: "DeathWatcherBot") -> None:
        while True:
            try:
                pending = await self.queue.get()
                try:
                    await pending.action()
                except Exception as exc:
                    await bot.error_reporter.report(bot, f"Action failed: {pending.label}", exc)
                await asyncio.sleep(self.delay_seconds)
            except asyncio.CancelledError:
                break


class DeathWatcherBot(commands.Bot):
    def __init__(self, config_path: Path) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.guilds = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config_loader = ConfigLoader(config_path)
        self.config = self.config_loader.load()
        self.audit = AuditLogger(Path(self.config.paths.audit_log_path))
        self.error_reporter = ErrorReporter(self.config.error_reporting, self.audit)
        self.users_repo = UsersRepository(Path(self.config.paths.users_db_path))
        self.cursor_repo = CursorRepository(Path(self.config.paths.cursor_cache_path))
        self.users_db = self.users_repo.load()
        self.cursor_map = self.cursor_repo.load()
        self.policy = ServerPolicy(self.config.policy)
        self.validator: SteamValidatorInterface = SteamWebApiValidator(
            self.config.steam.api_key,
            self.config.steam.timeout_seconds,
        )
        self.timers: Dict[str, datetime] = {}
        self.tailers = {
            server.server_id: LjsonTailer(
                Path(server.path_to_logs_directory),
                self.cursor_map.get(server.server_id, 0),
                TailerOptions(
                    tail_mode=self.config.legacy_logs.tail_mode,
                    backlog_max_lines=self.config.legacy_logs.backlog_max_lines,
                    strict_death_schema=self.config.legacy_logs.strict_death_schema,
                    archive_old_logs=self.config.legacy_logs.archive_old_logs,
                ),
            )
            for server in self.config.servers
        }
        self._background_tasks: List[asyncio.Task[None]] = []
        self.voice_action_queue = ActionQueue()
        self.voice_last_action: Dict[str, datetime] = {}

    async def setup_hook(self) -> None:
        self._background_tasks.append(asyncio.create_task(self._run_background_tasks()))
        self._background_tasks.append(asyncio.create_task(self._run_vc_check_loop()))
        self._background_tasks.append(asyncio.create_task(self._run_leaderboard_loop()))
        self._background_tasks.append(asyncio.create_task(self.voice_action_queue.run(self)))
        command_list = self._app_commands()
        if self.config.discord.guild_id:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            guild = discord.Object(id=self.config.discord.guild_id)
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            for command in command_list:
                self.tree.add_command(command, guild=guild)
            await self.tree.sync(guild=guild)
        else:
            self.tree.clear_commands(guild=None)
            for command in command_list:
                self.tree.add_command(command)
            await self.tree.sync()

    async def close(self) -> None:
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await super().close()

    async def _run_background_tasks(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.poll_logs()
                await self.process_timers()
            except Exception as exc:
                await self.error_reporter.report(self, "Background task failure", exc)
            await asyncio.sleep(2)

    async def _run_vc_check_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.vc_check_loop()
            except Exception as exc:
                await self.error_reporter.report(self, "VC check failure", exc)
            await asyncio.sleep(self.config.voice_enforcement_interval_seconds)

    async def _run_leaderboard_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.maybe_post_leaderboard()
            except Exception as exc:
                await self.error_reporter.report(self, "Leaderboard loop failure", exc)
            await asyncio.sleep(30)

    async def on_ready(self) -> None:
        self.audit.write(AuditEvent(event="bot_ready", message="Bot connected", context={}))

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return
        if self.config.discord.role_alive_id == 0:
            return
        user = self._get_user_by_discord_id(str(after.id))
        if not user:
            return
        alive_role = after.guild.get_role(self.config.discord.role_alive_id)
        dead_role = after.guild.get_role(self.config.discord.role_dead_id)
        if alive_role and alive_role in after.roles and user.dead:
            user.dead = False
            user.dead_until = None
            user.last_dead_at = None
            self.users_repo.save(self.users_db)
            await self._apply_unban_for_user(user, reason="admin_alive_role")
            if dead_role and dead_role in after.roles:
                await self.voice_action_queue.enqueue(
                    "remove_dead_role",
                    lambda: after.remove_roles(dead_role, reason="Alive role override"),
                )

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if not self.config.features.enable_voice_enforcement:
            return
        if not self._any_server_voice_enabled():
            return
        if not after.channel and not before.channel:
            return
        user_record = self._get_user_by_discord_id(str(member.id))
        if not user_record:
            return
        user_record.last_voice_channel_id = str(after.channel.id) if after.channel else None
        user_record.last_voice_seen_at = _utc_now().isoformat()
        self.users_repo.save(self.users_db)
        if not self._debounce_allowed(user_record.steam_id):
            return
        join_vc_id = self.config.discord.join_vc_id
        category_id = self.config.discord.join_vc_category_id
        guild = member.guild
        if after.channel and after.channel.id == join_vc_id:
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                return
            channel = discord.utils.get(category.voice_channels, name=str(member.id))
            if channel is None:
                channel = await guild.create_voice_channel(name=str(member.id), category=category)
            await self.voice_action_queue.enqueue(
                "move_to_private",
                lambda: member.move_to(channel),
            )
            if not user_record.dead:
                await self._apply_unban_for_user(user_record, reason="joined_private_vc", enforce_voice=True)
            return
        if before.channel and before.channel.name == str(member.id):
            if after.channel is None or after.channel.id != before.channel.id:
                if not user_record.dead:
                    await self._apply_ban_for_user(user_record, reason="left_private_vc", enforce_voice=True)
                if before.channel and len(before.channel.members) == 0:
                    await self.voice_action_queue.enqueue(
                        "delete_private_vc",
                        lambda: before.channel.delete(),
                    )

    def _any_server_voice_enabled(self) -> bool:
        return any(server.enable_voice_enforcement for server in self.config.servers)

    def _app_commands(self) -> List[app_commands.Command]:
        return [
            self.validatesteamid,
            self.validate,
            self.setserver,
            self.revive,
            self.ban,
            self.unban,
            self.userdata,
            self.delete_user_from_database,
            self.wipe,
        ]

    def _debounce_allowed(self, steam_id: str) -> bool:
        now = _utc_now()
        last = self.voice_last_action.get(steam_id)
        if last and (now - last).total_seconds() < self.config.voice_debounce_seconds:
            return False
        self.voice_last_action[steam_id] = now
        return True

    def _get_user_by_discord_id(self, discord_id: str) -> Optional[UserRecord]:
        for user in self.users_db.users.values():
            if user.discord_id == discord_id:
                return user
        return None

    def _parse_dead_until(self, user: UserRecord) -> Optional[datetime]:
        if not user.dead_until:
            return None
        return datetime.fromisoformat(user.dead_until)

    def _resolve_targets(self, user: UserRecord) -> List[str]:
        server_ids = [server.server_id for server in self.config.servers]
        return self.policy.resolve_active_servers(user, server_ids)

    def _resolve_whitelist_targets(self, user: UserRecord) -> List[str]:
        server_ids = [server.server_id for server in self.config.servers]
        return self.policy.resolve_whitelist_targets(user, server_ids)

    def _get_member(self, discord_id: str) -> Optional[discord.Member]:
        guild = self.get_guild(self.config.discord.guild_id)
        if guild is None:
            return None
        return guild.get_member(int(discord_id))

    async def _apply_role_swap(self, user: UserRecord, alive: bool) -> None:
        member = self._get_member(user.discord_id) if user.discord_id else None
        if not member:
            return
        alive_role = member.guild.get_role(self.config.discord.role_alive_id)
        dead_role = member.guild.get_role(self.config.discord.role_dead_id)
        if alive and alive_role:
            await self.voice_action_queue.enqueue(
                "add_alive_role",
                lambda: member.add_roles(alive_role, reason="revive"),
            )
        if not alive and dead_role:
            await self.voice_action_queue.enqueue(
                "add_dead_role",
                lambda: member.add_roles(dead_role, reason="death"),
            )
        if alive and dead_role:
            await self.voice_action_queue.enqueue(
                "remove_dead_role",
                lambda: member.remove_roles(dead_role, reason="revive"),
            )
        if not alive and alive_role:
            await self.voice_action_queue.enqueue(
                "remove_alive_role",
                lambda: member.remove_roles(alive_role, reason="death"),
            )

    async def _disconnect_from_private(self, user: UserRecord) -> None:
        member = self._get_member(user.discord_id) if user.discord_id else None
        if not member or not member.voice:
            return
        if member.voice.channel and member.voice.channel.name == str(member.id):
            await self.voice_action_queue.enqueue(
                "disconnect_member",
                lambda: member.move_to(None),
            )

    async def _apply_unban_for_user(self, user: UserRecord, reason: str, enforce_voice: bool = False) -> None:
        if user.dead:
            return
        targets = self._resolve_targets(user)
        for server in self.config.servers:
            if server.server_id not in targets or not server.enable_ban_sync:
                continue
            if enforce_voice and not server.enable_voice_enforcement:
                continue
            adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
            adapter.remove_from_ban(user.steam_id)
        await self._audit_discord("unban", user, reason=reason)

    async def _apply_ban_for_user(self, user: UserRecord, reason: str, enforce_voice: bool = False) -> None:
        targets = self._resolve_targets(user)
        for server in self.config.servers:
            if server.server_id not in targets or not server.enable_ban_sync:
                continue
            if enforce_voice and not server.enable_voice_enforcement:
                continue
            adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
            adapter.add_to_ban(user.steam_id)
        await self._audit_discord("ban", user, reason=reason)

    async def _audit_discord(self, action: str, user: UserRecord, reason: str) -> None:
        self.audit.write(
            AuditEvent(
                event=action,
                message=f"{action} applied",
                context={"steam_id": user.steam_id, "discord_id": user.discord_id, "reason": reason},
            )
        )
        channel = self.get_channel(self.config.discord.dump_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(f"{action.title()} applied for {user.steam_id} ({reason})")

    async def poll_logs(self) -> None:
        if not self.config.features.enable_deathwatcher:
            return
        guild = self.get_guild(self.config.discord.guild_id)
        for server in self.config.servers:
            if not server.enable_death_scanning:
                continue
            tailer = self.tailers[server.server_id]
            had_events = False
            for event in tailer.read_events(server.server_id) or []:
                had_events = True
                parsed = parse_death_event(event, strict_schema=self.config.legacy_logs.strict_death_schema)
                if not parsed:
                    continue
                steam_id = parsed["steam_id"]
                user = self.users_db.users.get(steam_id, UserRecord(steam_id=steam_id))
                user.dead = True
                user.last_alive_sec = parsed.get("alive_sec")
                user.death_count += 1
                user.last_dead_at = _utc_now().isoformat()
                user.last_death_server_id = server.server_id
                user.set_dead_until(_utc_now() + timedelta(minutes=self.config.ban_duration_minutes))
                self.users_db.users[steam_id] = user
                if server.enable_ban_sync:
                    adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
                    adapter.add_to_ban(steam_id)
                self.users_repo.save(self.users_db)
                if guild and user.discord_id:
                    await self._apply_role_swap(user, alive=False)
                    await self._disconnect_from_private(user)
                await self._audit_discord("death_detected", user, reason=f"server:{server.server_id}")
            if had_events:
                self.cursor_map[server.server_id] = tailer.cursor
                self.cursor_repo.save(self.cursor_map)

    async def process_timers(self) -> None:
        now = _utc_now()
        for user in self.users_db.users.values():
            if not user.dead or not user.dead_until:
                continue
            expires_at = self._parse_dead_until(user)
            if not expires_at or expires_at > now:
                continue
            user.dead = False
            user.dead_until = None
            self.users_repo.save(self.users_db)
            await self._apply_role_swap(user, alive=True)
            member = self._get_member(user.discord_id) if user.discord_id else None
            if member and member.voice and member.voice.channel and member.voice.channel.name == str(member.id):
                await self._apply_unban_for_user(user, reason="timer_expired_in_vc", enforce_voice=True)
            else:
                await self._audit_discord("revive_pending_vc", user, reason="timer_expired")

    async def vc_check_loop(self) -> None:
        if not self.config.features.enable_voice_enforcement:
            return
        guild = self.get_guild(self.config.discord.guild_id)
        if guild is None:
            return
        alive_role = guild.get_role(self.config.discord.role_alive_id)
        if alive_role is None:
            return
        for member in alive_role.members:
            user = self._get_user_by_discord_id(str(member.id))
            if not user:
                continue
            user.is_admin = any(role.id == self.config.discord.role_admin_id for role in member.roles)
            self.users_repo.save(self.users_db)
            if user.dead:
                continue
            in_private = member.voice and member.voice.channel and member.voice.channel.name == str(member.id)
            if in_private:
                await self._apply_unban_for_user(user, reason="vc_check_in_private", enforce_voice=True)
            else:
                await self._apply_ban_for_user(user, reason="vc_check_not_in_private", enforce_voice=True)

    async def maybe_post_leaderboard(self) -> None:
        if not self.config.leaderboard.enabled or not self.config.features.enable_leaderboard:
            return
        if self.config.leaderboard.schedule_minutes <= 0:
            return
        now = _utc_now()
        last = self.timers.get("leaderboard")
        if last and (now - last).total_seconds() < self.config.leaderboard.schedule_minutes * 60:
            return
        await self.post_leaderboard()
        self.timers["leaderboard"] = now

    def build_leaderboard(self) -> str:
        users = list(self.users_db.users.values())
        if self.config.leaderboard.metric == "death_count":
            ranked = sorted(users, key=lambda u: u.death_count, reverse=True)
            title = "Top Deaths"
            lines = [f"{idx+1}. {user.steam_id} — deaths: {user.death_count}" for idx, user in enumerate(ranked[:10])]
        else:
            ranked = sorted(users, key=lambda u: u.last_alive_sec or 0, reverse=True)
            title = "Top Survivors"
            lines = [
                f"{idx+1}. {user.steam_id} — aliveSec: {user.last_alive_sec or 0}" for idx, user in enumerate(ranked[:10])
            ]
        return "\n".join([title, *lines])

    async def post_leaderboard(self) -> None:
        channel = self.get_channel(self.config.discord.leaderboard_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(self.build_leaderboard())
            self.audit.write(AuditEvent(event="leaderboard_post", message="Leaderboard posted", context={}))

    def _require_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        if self.config.discord.role_admin_id == 0:
            return False
        return any(role.id == self.config.discord.role_admin_id for role in interaction.user.roles)

    async def _handle_validate(self, interaction: discord.Interaction, steam64: str) -> None:
        if self.config.discord.validate_steam_channel_id and (
            interaction.channel_id != self.config.discord.validate_steam_channel_id
        ):
            await interaction.response.send_message(
                f"Use the validation channel <#{self.config.discord.validate_steam_channel_id}>.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            is_valid = await self.validator.validate(steam64)
        except Exception as exc:
            await self.error_reporter.report(self, "Steam validation failed", exc)
            await interaction.followup.send("Validation failed (Steam API).", ephemeral=True)
            return
        if not is_valid:
            await interaction.followup.send("Invalid Steam64 ID.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64, UserRecord(steam_id=steam64))
        user.discord_id = str(interaction.user.id)
        user.dead = False
        user.dead_until = None
        user.last_dead_at = None
        self.users_db.users[steam64] = user
        for server in self.config.servers:
            adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
            if server.enable_whitelist_sync and server.server_id in self._resolve_whitelist_targets(user):
                adapter.add_to_whitelist(steam64)
            if server.enable_ban_sync:
                adapter.add_to_ban(steam64)
        self.users_repo.save(self.users_db)
        await self._apply_role_swap(user, alive=True)
        await interaction.followup.send("Validated and added to lists.", ephemeral=True)
        try:
            await interaction.user.send(
                "Validation complete. If you don't see a DM, check your privacy settings for this server."
            )
        except discord.Forbidden:
            pass

    @app_commands.command(name="validatesteamid", description="Validate a Steam64 ID")
    async def validatesteamid(self, interaction: discord.Interaction, steam64: str) -> None:
        await self._handle_validate(interaction, steam64)

    @app_commands.command(name="validate", description="Validate a Steam64 ID")
    async def validate(self, interaction: discord.Interaction, steam64: str) -> None:
        await self._handle_validate(interaction, steam64)

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
        if not self._require_admin(interaction):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64)
        if not user:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return
        user.dead = False
        user.dead_until = None
        user.last_dead_at = None
        self.users_repo.save(self.users_db)
        await self._apply_role_swap(user, alive=True)
        await self._apply_unban_for_user(user, reason="admin_revive")
        await interaction.response.send_message("User revived.", ephemeral=True)

    @app_commands.command(name="ban", description="Admin ban a user by Steam64")
    async def ban(self, interaction: discord.Interaction, steam64: str) -> None:
        if not self._require_admin(interaction):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64, UserRecord(steam_id=steam64))
        user.dead = True
        user.last_dead_at = _utc_now().isoformat()
        user.set_dead_until(_utc_now() + timedelta(minutes=self.config.ban_duration_minutes))
        self.users_db.users[steam64] = user
        self.users_repo.save(self.users_db)
        await self._apply_role_swap(user, alive=False)
        await self._apply_ban_for_user(user, reason="admin_ban")
        await interaction.response.send_message("User banned.", ephemeral=True)

    @app_commands.command(name="unban", description="Admin unban a user by Steam64")
    async def unban(self, interaction: discord.Interaction, steam64: str) -> None:
        if not self._require_admin(interaction):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(steam64)
        if not user:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return
        user.dead = False
        user.dead_until = None
        user.last_dead_at = None
        self.users_repo.save(self.users_db)
        await self._apply_role_swap(user, alive=True)
        await self._apply_unban_for_user(user, reason="admin_unban")
        await interaction.response.send_message("User unbanned.", ephemeral=True)

    @app_commands.command(name="userdata", description="Lookup user data by Steam64 or Discord ID")
    async def userdata(self, interaction: discord.Interaction, identifier: str) -> None:
        user = self.users_db.users.get(identifier)
        if not user:
            user = self._get_user_by_discord_id(identifier)
        if not user:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return
        payload = {
            "steam_id": user.steam_id,
            "discord_id": user.discord_id,
            "dead": user.dead,
            "dead_until": user.dead_until,
            "last_alive_sec": user.last_alive_sec,
            "active_server_id": user.active_server_id,
            "home_server_id": user.home_server_id,
            "last_death_server_id": user.last_death_server_id,
            "last_voice_channel_id": user.last_voice_channel_id,
            "last_voice_seen_at": user.last_voice_seen_at,
            "death_count": user.death_count,
            "is_admin": user.is_admin,
        }
        await interaction.response.send_message(f"```json\n{json.dumps(payload, indent=2)}\n```", ephemeral=True)

    @app_commands.command(name="delete_user_from_database", description="Delete a user record")
    async def delete_user_from_database(self, interaction: discord.Interaction, identifier: str) -> None:
        if not self._require_admin(interaction):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        user = self.users_db.users.get(identifier)
        if not user:
            user = self._get_user_by_discord_id(identifier)
        if not user:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return
        view = DeleteUserConfirmView(self, user)
        await interaction.response.send_message(
            f"Confirm delete for {user.steam_id}?",
            ephemeral=True,
            view=view,
        )

    @app_commands.command(name="wipe", description="Admin wipe all user data")
    async def wipe(self, interaction: discord.Interaction) -> None:
        if not self._require_admin(interaction):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        self.users_db = UsersDatabase()
        self.users_repo.save(self.users_db)
        await interaction.response.send_message("Database wiped.", ephemeral=True)


class DeleteUserConfirmView(discord.ui.View):
    def __init__(self, bot: DeathWatcherBot, user: UserRecord) -> None:
        super().__init__(timeout=30)
        self.bot = bot
        self.user = user

    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.bot.users_db.users.pop(self.user.steam_id, None)
        self.bot.users_repo.save(self.bot.users_db)
        if self.bot.config.delete_user_remove_lists:
            targets = self.bot._resolve_targets(self.user)
            for server in self.bot.config.servers:
                if server.server_id not in targets:
                    continue
                adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
                adapter.remove_from_ban(self.user.steam_id)
                adapter.remove_from_whitelist(self.user.steam_id)
        await interaction.response.send_message("User deleted.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Delete cancelled.", ephemeral=True)
        self.stop()
