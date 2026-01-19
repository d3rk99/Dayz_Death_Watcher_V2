from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Set
from ..core.utils import atomic_write_locked, read_lines_locked


@dataclass
class ServerLists:
    ban_list_path: Path
    whitelist_path: Path


class DayZListAdapter:
    def __init__(self, paths: ServerLists) -> None:
        self.paths = paths

    def _load_set(self, path: Path) -> Set[str]:
        return {line.strip() for line in read_lines_locked(path) if line.strip()}

    def _save_set(self, path: Path, values: Iterable[str]) -> None:
        content = "\n".join(sorted(set(values))) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_locked(path, content)

    def add_to_ban(self, steam_id: str) -> None:
        entries = self._load_set(self.paths.ban_list_path)
        entries.add(steam_id)
        self._save_set(self.paths.ban_list_path, entries)

    def remove_from_ban(self, steam_id: str) -> None:
        entries = self._load_set(self.paths.ban_list_path)
        entries.discard(steam_id)
        self._save_set(self.paths.ban_list_path, entries)

    def add_to_whitelist(self, steam_id: str) -> None:
        entries = self._load_set(self.paths.whitelist_path)
        entries.add(steam_id)
        self._save_set(self.paths.whitelist_path, entries)

    def remove_from_whitelist(self, steam_id: str) -> None:
        entries = self._load_set(self.paths.whitelist_path)
        entries.discard(steam_id)
        self._save_set(self.paths.whitelist_path, entries)

    def read_ban_list(self) -> Set[str]:
        return self._load_set(self.paths.ban_list_path)

    def read_whitelist(self) -> Set[str]:
        return self._load_set(self.paths.whitelist_path)
