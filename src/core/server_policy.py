from __future__ import annotations

from typing import Iterable, List, Optional
from .config import PolicyConfig
from .persistence import UserRecord


class ServerPolicy:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def resolve_active_servers(self, user: UserRecord, configured_server_ids: Iterable[str]) -> List[str]:
        configured = list(configured_server_ids)
        if not configured:
            return []
        if self.config.mode == "all_servers":
            return configured
        if self.config.mode == "per_user_server":
            if user.home_server_id and user.home_server_id in configured:
                return [user.home_server_id]
            return []
        if user.active_server_id and user.active_server_id in configured:
            return [user.active_server_id]
        if self.config.default_active_server_id in configured:
            return [self.config.default_active_server_id]
        return [configured[0]]

    def resolve_whitelist_targets(self, user: UserRecord, configured_server_ids: Iterable[str]) -> List[str]:
        configured = list(configured_server_ids)
        if self.config.whitelist_on_validate == "active_server":
            return self.resolve_active_servers(user, configured)
        return configured
