from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass
class DiscordConfig:
    token: str = ""
    guild_id: int = 0
    role_alive_id: int = 0
    role_dead_id: int = 0
    role_admin_id: int = 0
    validate_steam_channel_id: int = 0
    dump_channel_id: int = 0
    join_vc_id: int = 0
    join_vc_category_id: int = 0
    leaderboard_channel_id: int = 0


@dataclass
class ErrorReportingConfig:
    error_dump_channel_id: int = 0
    error_dump_allow_mention: bool = False
    error_dump_mention_tag: str = ""
    error_dump_rate_limit_seconds: int = 120
    error_dump_include_traceback: bool = True


@dataclass
class SteamApiConfig:
    api_key: str = ""
    timeout_seconds: int = 6


@dataclass
class ServerConfig:
    server_id: str
    path_to_logs_directory: str
    path_to_bans: str
    path_to_whitelist: str
    enable_death_scanning: bool = True
    enable_voice_enforcement: bool = True
    enable_whitelist_sync: bool = True
    enable_ban_sync: bool = True


@dataclass
class FeatureToggles:
    enable_deathwatcher: bool = True
    enable_voice_enforcement: bool = True
    enable_leaderboard: bool = True
    enable_discord_cogs: List[str] = field(default_factory=list)


@dataclass
class LeaderboardConfig:
    enabled: bool = True
    schedule_minutes: int = 0
    metric: str = "longest_alive"


@dataclass
class PolicyConfig:
    mode: str = "single_active_server"  # single_active_server, all_servers, per_user_server
    default_active_server_id: Optional[str] = None
    whitelist_on_validate: str = "all_servers"  # all_servers, active_server


@dataclass
class PathsConfig:
    data_dir: str = "data"
    users_db_path: str = "data/userdata_db.json"
    cursor_cache_path: str = "data/cursor_cache.json"
    audit_log_path: str = "data/audit.log"


@dataclass
class LegacyLogOptions:
    tail_mode: str = "newest_only"  # newest_only, newest_with_backlog
    backlog_max_lines: int = 200
    strict_death_schema: bool = True
    archive_old_logs: bool = False


@dataclass
class AppConfig:
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    error_reporting: ErrorReportingConfig = field(default_factory=ErrorReportingConfig)
    steam: SteamApiConfig = field(default_factory=SteamApiConfig)
    servers: List[ServerConfig] = field(default_factory=list)
    paths: PathsConfig = field(default_factory=PathsConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    features: FeatureToggles = field(default_factory=FeatureToggles)
    leaderboard: LeaderboardConfig = field(default_factory=LeaderboardConfig)
    legacy_logs: LegacyLogOptions = field(default_factory=LegacyLogOptions)
    ban_duration_minutes: int = 30
    verbose_logs: bool = False
    voice_enforcement_interval_seconds: int = 10
    voice_debounce_seconds: int = 4
    delete_user_remove_lists: bool = True

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AppConfig":
        discord = DiscordConfig(**data.get("discord", {}))
        error_reporting = ErrorReportingConfig(**data.get("error_reporting", {}))
        steam = SteamApiConfig(**data.get("steam", {}))
        servers = [ServerConfig(**item) for item in data.get("servers", [])]
        paths = PathsConfig(**data.get("paths", {}))
        policy = PolicyConfig(**data.get("policy", {}))
        features = FeatureToggles(**data.get("features", {}))
        leaderboard = LeaderboardConfig(**data.get("leaderboard", {}))
        legacy_logs = LegacyLogOptions(**data.get("legacy_logs", {}))
        return AppConfig(
            discord=discord,
            error_reporting=error_reporting,
            steam=steam,
            servers=servers,
            paths=paths,
            policy=policy,
            features=features,
            leaderboard=leaderboard,
            legacy_logs=legacy_logs,
            ban_duration_minutes=data.get("ban_duration_minutes", 30),
            verbose_logs=data.get("verbose_logs", False),
            voice_enforcement_interval_seconds=data.get("voice_enforcement_interval_seconds", 10),
            voice_debounce_seconds=data.get("voice_debounce_seconds", 4),
            delete_user_remove_lists=data.get("delete_user_remove_lists", True),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfigLoader:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppConfig:
        if not self.path.exists():
            raise FileNotFoundError(f"Config not found: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(config.to_dict(), indent=2, sort_keys=False),
            encoding="utf-8",
        )
