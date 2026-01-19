from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import json


@dataclass
class UserRecord:
    steam_id: str
    discord_id: Optional[str] = None
    dead: bool = False
    last_alive_sec: Optional[int] = None
    active_server_id: Optional[str] = None
    home_server_id: Optional[str] = None
    death_count: int = 0


@dataclass
class UsersDatabase:
    users: Dict[str, UserRecord] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {steam_id: vars(record) for steam_id, record in self.users.items()}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "UsersDatabase":
        users = {
            steam_id: UserRecord(**payload)
            for steam_id, payload in data.items()
        }
        return UsersDatabase(users=users)


class JsonStore:
    def __init__(self, path: Path, default: Dict[str, Any]) -> None:
        self.path = path
        self.default = default

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self.default
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class UsersRepository:
    def __init__(self, path: Path) -> None:
        self.store = JsonStore(path, default={})

    def load(self) -> UsersDatabase:
        return UsersDatabase.from_dict(self.store.load())

    def save(self, database: UsersDatabase) -> None:
        self.store.save(database.to_dict())


class CursorRepository:
    def __init__(self, path: Path) -> None:
        self.store = JsonStore(path, default={})

    def load(self) -> Dict[str, int]:
        return {key: int(value) for key, value in self.store.load().items()}

    def save(self, cursor_map: Dict[str, int]) -> None:
        self.store.save({key: int(value) for key, value in cursor_map.items()})
