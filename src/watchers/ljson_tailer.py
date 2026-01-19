from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional
import json


@dataclass
class LogEvent:
    server_id: str
    raw: str
    data: Optional[dict]


class LjsonTailer:
    def __init__(self, logs_dir: Path, cursor: int = 0) -> None:
        self.logs_dir = logs_dir
        self.cursor = cursor
        self.active_file: Optional[Path] = None

    def _find_latest_file(self) -> Optional[Path]:
        if not self.logs_dir.exists():
            return None
        candidates = sorted(self.logs_dir.glob("dl_*.ljson"), key=lambda p: p.stat().st_mtime)
        return candidates[-1] if candidates else None

    def ensure_latest(self) -> bool:
        latest = self._find_latest_file()
        if latest is None:
            return False
        if self.active_file != latest:
            self.active_file = latest
            self.cursor = 0
        return True

    def read_events(self, server_id: str) -> Iterator[LogEvent]:
        if not self.ensure_latest() or self.active_file is None:
            return
        with self.active_file.open("r", encoding="utf-8") as handle:
            handle.seek(self.cursor)
            while True:
                line = handle.readline()
                if not line:
                    break
                self.cursor = handle.tell()
                line = line.strip()
                if not line:
                    continue
                data = None
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    pass
                yield LogEvent(server_id=server_id, raw=line, data=data)


def parse_death_event(event: LogEvent) -> Optional[dict]:
    if not event.data:
        return None
    if event.data.get("event") != "PLAYER_DEATH":
        return None
    player = event.data.get("player", {})
    steam_id = player.get("steamId")
    if not steam_id:
        return None
    return {
        "steam_id": steam_id,
        "alive_sec": player.get("aliveSec"),
        "raw": event.data,
    }
